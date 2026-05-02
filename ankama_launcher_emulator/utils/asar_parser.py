"""Minimal read-only parser for Electron ASAR archives.

Implements just enough of the ASAR format to extract individual files
without external dependencies.
"""

import json
import struct
from pathlib import Path
from typing import BinaryIO, Dict, Any, Union


def _walk_tree(tree: Dict[str, Any], parts: list[str]) -> Dict[str, Any]:
    """Walk the ASAR header tree to find a file node."""
    node = tree
    for part in parts:
        if part == "":
            continue
        files = node.get("files")
        if not isinstance(files, dict):
            raise FileNotFoundError(f"ASAR: '{ '/'.join(parts)}' not found")
        node = files.get(part)
        if node is None:
            raise FileNotFoundError(f"ASAR: '{ '/'.join(parts)}' not found")
    return node


def read_file_from_asar(asar_path: Union[str, Path], internal_path: Union[str, Path]) -> bytes:
    """Read a single file from an ASAR archive.

    Args:
        asar_path: Path to the .asar archive.
        internal_path: Path inside the archive (e.g. "package.json").

    Returns:
        Raw bytes of the extracted file.

    Raises:
        FileNotFoundError: If the archive or internal file does not exist.
    """
    asar_path = Path(asar_path)
    if not asar_path.exists():
        raise FileNotFoundError(f"ASAR archive not found: {asar_path}")

    internal_path = Path(internal_path)
    parts = list(internal_path.parts)

    with asar_path.open("rb") as f:
        # Header: 4 uint32LE values
        header = f.read(16)
        if len(header) != 16:
            raise ValueError(f"Invalid ASAR header in {asar_path}")

        data_size, header_size, header_object_size, header_string_size = struct.unpack("<4I", header)

        # Read and parse JSON header
        json_bytes = f.read(header_string_size)
        if len(json_bytes) != header_string_size:
            raise ValueError(f"Truncated ASAR header in {asar_path}")

        header_json = json.loads(json_bytes.decode("utf-8"))

        # Base offset where file data starts
        base_offset = 8 + header_size

        # Walk tree to find file
        node = _walk_tree(header_json, parts)

        if "files" in node:
            raise IsADirectoryError(f"ASAR: '{internal_path}' is a directory")
        if "link" in node:
            # Symbolic link – resolve relative to archive root
            link_target = Path(node["link"])
            return read_file_from_asar(asar_path, link_target)

        size = node["size"]
        offset = int(node["offset"])

        f.seek(base_offset + offset)
        data = f.read(size)
        if len(data) != size:
            raise ValueError(f"ASAR: short read for '{internal_path}'")

        return data


def extract_file_from_asar(
    asar_path: Union[str, Path],
    internal_path: Union[str, Path],
    destination: Union[str, Path],
) -> None:
    """Extract a single file from an ASAR archive to disk."""
    data = read_file_from_asar(asar_path, internal_path)
    dest_path = Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(data)
