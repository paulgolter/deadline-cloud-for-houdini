# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

import pytest
from unittest import mock
from .mock_hou import hou_module as hou
from deadline.houdini_submitter.python.deadline_cloud_for_houdini._assets import (
    _get_scene_asset_references,
    _get_output_directories,
    _parse_files,
)
from deadline.client.job_bundle.submission import AssetReferences


def test_get_scene_asset_references():
    hou.hscript.return_value = (
        "1 [ ] /out/mantra1 \t( 1 5 1 )\n2 [ 1 ] /out/karma1/lopnet/rop_usdrender \t( 1 5 1 )\n",
        "",
    )
    node = hou.node
    hou.node.type().name.return_value = "deadline-cloud"
    mock_parm = hou.Parm
    hou.Parm.node.return_value = node
    hou.Parm.name.return_value = "shadowmap_file"
    hou.node.type().nameWithCategory.return_value = "Driver/ifd"
    hou.hipFile.path.return_value = "/some/path/test.hip"
    hou.node.parm().eval.return_value = "/tmp/foo.$F.exr"

    dir_parm = mock.Mock()
    dir_parm.node.return_value = None
    dir_parm.evalAsString.return_value = "/path/assets/"

    file_parm = mock.Mock()
    file_parm.node.return_value = None
    file_parm.evalAsString.return_value = "/path/asset.png"

    hou.fileReferences.return_value = (
        # These references should be resolved and added as job attachments
        (dir_parm, "$HIP/houdini19.5/"),
        (file_parm, "$HIP/houdini19.5/otls/Deadline-Cloud.hda"),
        # These references should all be skipped based on their reference prefix
        (mock_parm, "opdef:$OS.rat"),
        (mock_parm, "oplib:$OS.rat"),
        (mock_parm, "temp:$OS.rat"),
        (mock_parm, "op:$OS.rat"),
    )
    mock_os = mock.Mock()
    mock_os.path.isdir = lambda path: path.endswith("/")
    mock_os.path.isfile = lambda path: not path.endswith("/")

    with mock.patch(
        "deadline.houdini_submitter.python.deadline_cloud_for_houdini._assets.os", mock_os
    ):
        asset_refs = _get_scene_asset_references(node)

    assert asset_refs.input_filenames == {"/path/asset.png", "/some/path/test.hip"}
    assert asset_refs.input_directories == {"/path/assets/"}
    assert asset_refs.output_directories == set()


def test_get_output_directories():
    """
    Test that given a node, the type name and category are mapped correctly to
    determine the parm to get the output directory from and return it.
    """
    node = hou.node
    node.type().nameWithCategory.return_value = "Driver/geometry"
    node.parm().eval.return_value = "/test/directory/detection/output.png"

    output_directories = _get_output_directories(node)

    node.parm.assert_called_with("sopoutput")
    assert output_directories == {"/test/directory/detection"}


@pytest.mark.parametrize(
    ("node_type", "output_parm_name"), [("Driver/fetch", "source"), ("Driver/wedge", "driver")]
)
def test_get_recursive_output_directories(node_type: str, output_parm_name: str):
    """
    Test output directory detection for fetch and wedge nodes that recursively
    find the output directories.
    """
    inner_node = mock.MagicMock()
    inner_node.type().nameWithCategory.return_value = "Driver/ifd"
    inner_node.parm().eval.return_value = "/test/output/directory/mantra/test.png"
    node = hou.node
    node.type().nameWithCategory.return_value = node_type
    node.node.return_value = inner_node

    out_dirs = _get_output_directories(node)

    node.parm.assert_called_once_with(output_parm_name)
    inner_node.parm.assert_called_with("vm_picture")
    assert out_dirs == {"/test/output/directory/mantra"}


@pytest.mark.parametrize(
    "auto_detected_assets, current_assets, prev_auto_detected_assets, expected_input_filenames, expected_input_directories, expected_output_directories",
    [
        pytest.param(
            AssetReferences(), AssetReferences(), AssetReferences(), [], [], [], id="no assets"
        ),
        pytest.param(
            AssetReferences(input_filenames={"/users/testuser/input.png"}),
            AssetReferences(),
            AssetReferences(),
            ["/users/testuser/input.png"],
            [],
            [],
            id="single auto detected asset",
        ),
        pytest.param(
            AssetReferences(
                input_filenames={"/users/testuser/input.png"},
                input_directories={"/users/testuser/input"},
            ),
            AssetReferences(
                input_filenames={
                    "/users/testuser/someotherfile.png",
                    "/users/testuser/input.png",
                    "/users/testuser/manuallyaddedfile.jpg",
                },
                output_directories={"/user/testuser/render"},
            ),
            AssetReferences(),
            [
                "/users/testuser/manuallyaddedfile.jpg",
                "/users/testuser/someotherfile.png",
                "/users/testuser/input.png",
            ],
            ["/users/testuser/input"],
            ["/user/testuser/render"],
            id="multiple auto detected and manual assets",
        ),
        pytest.param(
            AssetReferences(
                input_filenames={"/users/testuser/input_1.png"},
                input_directories={"/users/testuser/input_1"},
                output_directories={"/users/testuser/output_1"},
            ),
            AssetReferences(
                input_filenames={"/users/testuser/input_1.png", "/users/testuser/input_2.png"},
                input_directories={"/users/testuser/input_1", "/users/testuser/input_2"},
                output_directories={
                    "/users/testuser/output_1",
                    "/users/testuser/output_2",
                    "/users/testuser/manual_output_1",
                },
            ),
            AssetReferences(
                input_filenames={"/users/testuser/input_1.png", "/users/testuser/input_2.png"},
                input_directories={"/users/testuser/input_1", "/users/testuser/input_2"},
                output_directories={"/users/testuser/output_1", "/users/testuser/output_2"},
            ),
            ["/users/testuser/input_1.png"],
            ["/users/testuser/input_1"],
            ["/users/testuser/manual_output_1", "/users/testuser/output_1"],
            id="Removal of previously auto detected assets",
        ),
    ],
)
def test_parse_files_manually_added(
    auto_detected_assets: AssetReferences,
    current_assets: AssetReferences,
    prev_auto_detected_assets: AssetReferences,
    expected_input_filenames: list[str],
    expected_input_directories: list[str],
    expected_output_directories: list[str],
) -> None:
    """
    Test that parsing the scene for files correctly puts any non-detected files
    that may have been manually added at the front of the list and keeps them
    when called.
    """

    with (
        mock.patch(
            "deadline.houdini_submitter.python.deadline_cloud_for_houdini._assets._get_scene_asset_references"
        ) as mock_get_scene_assets,
        mock.patch(
            "deadline.houdini_submitter.python.deadline_cloud_for_houdini._assets._get_asset_references"
        ) as mock_get_asset_references,
        mock.patch(
            "deadline.houdini_submitter.python.deadline_cloud_for_houdini._assets._update_paths_parm"
        ) as mock_update_paths_parm,
        mock.patch(
            "deadline.houdini_submitter.python.deadline_cloud_for_houdini._assets._get_saved_auto_detected_asset_references"
        ) as mock_get_saved_auto_asset_references,
    ):
        mock_get_scene_assets.return_value = auto_detected_assets
        mock_get_asset_references.return_value = current_assets
        mock_get_saved_auto_asset_references.return_value = prev_auto_detected_assets

        node = hou.node
        _parse_files(node)

        mock_get_scene_assets.assert_called_once()
        mock_get_asset_references.assert_called_once()
        mock_get_saved_auto_asset_references.assert_called_once()
        mock_update_paths_parm.assert_has_calls(
            [
                mock.call(node, "input_filenames", expected_input_filenames),
                mock.call(node, "input_directories", expected_input_directories),
                mock.call(node, "output_directories", expected_output_directories),
                mock.call(node, "auto_input_filenames", list(auto_detected_assets.input_filenames)),
                mock.call(
                    node, "auto_input_directories", list(auto_detected_assets.input_directories)
                ),
                mock.call(
                    node, "auto_output_directories", list(auto_detected_assets.output_directories)
                ),
            ]
        )
        assert mock_update_paths_parm.call_count == 6
