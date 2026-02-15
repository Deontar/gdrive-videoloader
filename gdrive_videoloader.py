from urllib.parse import unquote
import requests
import argparse
import sys
from tqdm import tqdm
import os
import re
from bs4 import BeautifulSoup

def extract_drive_id(input_str: str) -> str:
    """Extracts the Google Drive file ID from a URL or returns the input if it's already an ID."""
    pattern = r'/file/d/([a-zA-Z0-9_-]+)'
    match = re.search(pattern, input_str)
    if match:
        return match.group(1)
    return input_str


def extract_bulk_data_ids_from_folder(url: str, verbose: bool) -> list[str]:
    """Extracts all data-id values from the DOM of a given folder URL using regex.
    Removes duplicates while preserving the first-seen order.
    """
    if verbose:
        print(f"[INFO] Fetching folder URL: {url}")
    try:
        response = requests.get(url)
        response.raise_for_status()
        text = response.text
        pattern = r'data-id\s*=\s*["\']([^"\']+)["\']'
        matches = re.findall(pattern, text)

        data_ids = []
        seen = set()
        for data_id in matches:
            # Skip invalid short ids
            if len(data_id) < 5:
                continue
            if data_id not in seen:
                data_ids.append(data_id)
                seen.add(data_id)

        if verbose:
            print(f"[INFO] Total unique data-ids found: {len(data_ids)}")
        return data_ids
    except requests.exceptions.RequestException as e:
        print(f"Error fetching folder URL: {e}")
        return []

def create_bulk_video_id_drive_url(video_id: str) -> str:
    """Create a get_video_info URL for a single video id."""
    return f'https://drive.google.com/u/0/get_video_info?docid={video_id}&drive_originator_app=303'

def sanitize_filename(name: str) -> str:
    if not name:
        return name
    invalid = r'<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, '_')
    return name.strip()

def download_from_video_id(video_id: str, output_file: str | None, chunk_size: int, verbose: bool) -> None:
    """Download a single video by its Drive video id (docid)."""
    drive_url = create_bulk_video_id_drive_url(video_id)
    if verbose:
        print(f"[INFO] Accessing {drive_url}")
    response = requests.get(drive_url)
    response.raise_for_status()
    page_content = response.text
    cookies = response.cookies.get_dict()

    video, title = get_video_url(page_content, verbose)
    filename = output_file if output_file else sanitize_filename(title) or video_id
    if video:
        download_file(video, cookies, filename, chunk_size, verbose)
    else:
        print(f"Unable to retrieve the video URL for id {video_id}.")

def extract_bulk_data_ids_from_folder(url: str, verbose: bool) -> list[str]:
    """Extracts all data-id values from the DOM of a given URL."""
    if verbose:
        print(f"[INFO] Fetching URL: {url}")
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        # Extract data-id attributes using regex and remove duplicates while
        # preserving the first-seen order.
        text = response.text
        pattern = r'data-id\s*=\s*["\']([^"\']+)["\']'
        matches = re.findall(pattern, text)

        data_ids = []
        seen = set()
        for data_id in matches:
            # Skip obviously-invalid short ids
            if len(data_id) < 5:
                continue
            if data_id not in seen:
                data_ids.append(data_id)
                seen.add(data_id)
        
        if verbose:
            print(f"[INFO] Total unique data-ids found: {len(data_ids)}")
            for id in data_ids:
                print(f"[INFO] Found data-id: {id}")
        return data_ids

    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")
        return []

def get_video_url(page_content: str, verbose: bool) -> tuple[str, str]:
    """Extracts the video playback URL and title from the page content."""
    if verbose:
        print("[INFO] Parsing video playback URL and title.")
    contentList = page_content.split("&")
    video, title = None, None
    for content in contentList:
        if content.startswith('title=') and not title:
            title = unquote(content.split('=')[-1])
        elif "videoplayback" in content and not video:
            video = unquote(content).split("|")[-1]
        if video and title:
            break

    if verbose:
        print(f"[INFO] Video URL: {video}")
        print(f"[INFO] Video Title: {title}")
    return video, title

def download_file(url: str, cookies: dict, filename: str, chunk_size: int, verbose: bool) -> None:
    """Downloads the file from the given URL with provided cookies, supports resuming."""
    headers = {}
    file_mode = 'wb'

    downloaded_size = 0
    if os.path.exists(filename):
        downloaded_size = os.path.getsize(filename)
        headers['Range'] = f"bytes={downloaded_size}-"
        file_mode = 'ab'

    if verbose:
        print(f"[INFO] Starting download from {url}")
        if downloaded_size > 0:
            print(f"[INFO] Resuming download from byte {downloaded_size}")

    response = requests.get(url, stream=True, cookies=cookies, headers=headers)
    if response.status_code in (200, 206):  # 200 for new downloads, 206 for partial content
        total_size = int(response.headers.get('content-length', 0)) + downloaded_size
        with open(filename, file_mode) as file:
            with tqdm(total=total_size, initial=downloaded_size, unit='B', unit_scale=True, desc=filename, file=sys.stdout) as pbar:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        file.write(chunk)
                        pbar.update(len(chunk))
        print(f"\n{filename} downloaded successfully.")
    else:
        print(f"Error downloading {filename}, status code: {response.status_code}")

def main(video_id_or_url: str, output_file: str = None, chunk_size: int = 1024, verbose: bool = False) -> None:
    """Main function to process video ID or URL and download the video file."""
    # If URL looks like a folder, extract all data-ids and process in bulk
    if '/folders/' in video_id_or_url:
        if verbose:
            print(f"[INFO] Detected folder URL, extracting data-ids from: {video_id_or_url}")
        data_ids = extract_bulk_data_ids_from_folder(video_id_or_url, verbose)
        if not data_ids:
            print("No data-IDs found in folder URL.")
            return

        for idx, data_id in enumerate(data_ids, 1):
            if verbose:
                print(f"\n[INFO] ({idx}/{len(data_ids)}) Processing id: {data_id}")
            try:
                download_from_video_id(data_id, output_file, chunk_size, verbose)
            except requests.exceptions.RequestException as e:
                print(f"Error accessing video info for {data_id}: {e}")
        return

    # Otherwise treat input as single video id or URL
    video_id = extract_drive_id(video_id_or_url)
    if verbose:
        print(f"[INFO] Extracted video ID: {video_id}")

    try:
        download_from_video_id(video_id, output_file, chunk_size, verbose)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching video info: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Script to download videos from Google Drive.")
    parser.add_argument("video_id", type=str, help="The video ID from Google Drive or a full Google Drive URL (e.g., 'abc-Qt12kjmS21kjDm2kjd' or 'https://drive.google.com/file/d/ID/view').")
    parser.add_argument("-o", "--output", type=str, help="Optional output file name for the downloaded video (default: video name in gdrive).")
    parser.add_argument("-c", "--chunk_size", type=int, default=1024, help="Optional chunk size (in bytes) for downloading the video. Default is 1024 bytes.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose mode.")
    parser.add_argument("--extract-ids", type=str, help="Extract all data-id values from a given URL (e.g., Google Drive folder URL).")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0")

    args = parser.parse_args()
    main(args.video_id, args.output, args.chunk_size, args.verbose)