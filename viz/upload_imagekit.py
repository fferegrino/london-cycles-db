"""Upload a file to ImageKit, replacing any file of the same name.

The README embeds images from ImageKit rather than from the repo, so refreshing
them does not add a commit to `main` every day.
"""

import os
from pathlib import Path

import typer


def upload_to_imagekit(
    file_path: Path,
    file_name: str | None = None,
    folder: str = "/projects/london-cycles-db",
    private_key: str | None = None,
    public_key: str | None = None,
) -> None:
    from imagekitio import ImageKit

    key = private_key or os.environ.get("IMAGEKIT_PRIVATE_KEY")
    pub_key = public_key or os.environ.get("IMAGEKIT_PUBLIC_KEY")
    if not key:
        raise ValueError(
            "ImageKit private key not provided. Set IMAGEKIT_PRIVATE_KEY environment variable or pass --imagekit-private-key."
        )

    ik = ImageKit(private_key=key)
    target_name = file_name or file_path.name
    normalized_folder = f"/{folder.strip('/')}" if folder else "/"

    print(f"Uploading {file_path} to ImageKit as {target_name} in folder '{normalized_folder}'...")

    upload_kwargs = {
        "file": file_path.read_bytes(),
        "file_name": target_name,
        "folder": normalized_folder,
        "use_unique_file_name": False,
        "overwrite_file": True,
    }
    if pub_key:
        upload_kwargs["public_key"] = pub_key

    upload_response = ik.files.upload(**upload_kwargs)
    file_url = getattr(upload_response, "url", None)
    if file_url:
        print(f"Uploaded successfully to ImageKit: {file_url}")
    else:
        print(f"Uploaded successfully to ImageKit: {upload_response}")


def main(
    file_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="File to upload."),
    file_name: str | None = typer.Option(None, "--file-name", help="Name in ImageKit. Defaults to the file's name."),
    folder: str = typer.Option("/projects/london-cycles-db", "--folder", help="Folder in ImageKit."),
):
    upload_to_imagekit(file_path=file_path, file_name=file_name, folder=folder)


if __name__ == "__main__":
    typer.run(main)
