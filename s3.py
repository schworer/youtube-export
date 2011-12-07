import logging
import os
import re
import shutil
import tempfile
import time
import unicodedata
import urllib2

from util import popen_results

def get_or_create_unconverted_source_url(video):

    # TODO: undone

                if not s3_url:

                    logging.info("Unconverted video not available on s3 yet, download from youtube and create it.")

                    video_path, thumbnail_time = youtube.download(video)
                    logging.info("Downloaded video to %s" % video_path)

                    assert(video_path)
                    assert(thumbnail_time)

                    s3_url = s3.upload_unconverted_to_s3(youtube_id, video_path)
                    logging.info("Uploaded unconverted video to %s for conversion" % s3_url)

                    os.remove(video_path)
                    logging.info("Deleted %s" % video_path)


def upload_unconverted_to_s3(youtube_id, video_path):

    s3_url = "s3://KA-youtube-unconverted/%s/%s" % (youtube_id, os.path.basename(video_path))

    command_args = ["s3cmd/s3cmd", "-c", "secrets/s3.s3cfg", "--acl-public", "put", video_path, s3_url]
    results = popen_results(command_args)
    logging.info(results)

    return s3_url

def list_converted_videos():

    videos = []
    s3_url = "s3://KA-youtube-converted"

    command_args = ["s3cmd/s3cmd", "-c", "secrets/s3.s3cfg", "ls", s3_url]
    results = popen_results(command_args)

    regex = re.compile("s3://KA-youtube-converted/(.+)/")

    for match in regex.finditer(results):
        videos.append({
                "url": match.group(),
                "youtube_id": match.groups()[0]
            })

    return videos

def clean_up_video_on_s3(youtube_id):

    s3_unconverted_url = "s3://KA-youtube-unconverted/%s/" % youtube_id
    s3_converted_url = "s3://KA-youtube-converted/%s/" % youtube_id

    command_args = ["s3cmd/s3cmd", "-c", "secrets/s3.s3cfg", "--recursive", "del", s3_unconverted_url]
    results = popen_results(command_args)
    logging.info(results)

    command_args = ["s3cmd/s3cmd", "-c", "secrets/s3.s3cfg", "--recursive", "del", s3_converted_url]
    results = popen_results(command_args)
    logging.info(results)

def download_converted_from_s3(youtube_id):

    s3_folder_url = "s3://KA-youtube-converted/%s/" % youtube_id

    temp_dir = tempfile.gettempdir()
    video_folder_path = os.path.join(temp_dir, youtube_id)

    if os.path.exists(video_folder_path):
        shutil.rmtree(video_folder_path)

    os.mkdir(video_folder_path)

    command_args = ["s3cmd/s3cmd", "-c", "secrets/s3.s3cfg", "--recursive", "get", s3_folder_url, video_folder_path]
    results = popen_results(command_args)
    logging.info(results)

    return video_folder_path

def upload_converted_to_archive(video):

    youtube_id = video["youtube_id"]

    video_folder_path = download_converted_from_s3(youtube_id)
    assert(video_folder_path)
    assert(len(os.listdir(video_folder_path)))
    logging.info("Downloaded youtube id %s from s3 for archive export" % youtube_id)

    archive_bucket_url = "s3://KA-converted-%s" % youtube_id

    # Only pass ascii title and descriptions in headers to archive
    ascii_title = unicodedata.normalize("NFKD", video["title"] or u"").encode("ascii", "ignore")
    ascii_description = unicodedata.normalize("NFKD", video["description"] or u"").encode("ascii", "ignore")

    # Newlines not welcome in headers
    ascii_title = ascii_title.replace("\n", " ")
    ascii_description = ascii_description.replace("\n", " ")

    command_args = [
            "s3cmd/s3cmd", 
            "-c", "secrets/archive.s3cfg", 
            "--recursive", 
            "--force", 
            "--add-header", "x-archive-auto-make-bucket:1",
            "--add-header", "x-archive-meta-collection:khanacademy", 
            "--add-header", "x-archive-meta-title:%s" % ascii_title,
            "--add-header", "x-archive-meta-description:%s" % ascii_description,
            "--add-header", "x-archive-meta-mediatype:movies", 
            "--add-header", "x-archive-meta01-subject:Salman Khan", 
            "--add-header", "x-archive-meta02-subject:Khan Academy", 
            "put", video_folder_path + "/", archive_bucket_url]
    results = popen_results(command_args)
    logging.info(results)

    logging.info("Waiting 10 seconds")
    time.sleep(10)

    shutil.rmtree(video_folder_path)
    logging.info("Cleaned up local video folder path")

    return verify_archive_upload(youtube_id)

def verify_archive_upload(youtube_id):

    c_retries_allowed = 3
    c_retries = 0

    while c_retries < c_retries_allowed:
        try:
            request = urllib2.Request("http://s3.us.archive.org/KA-converted-%s/%s.mp4" % (youtube_id, youtube_id))

            request.get_method = lambda: "HEAD"
            response = urllib2.urlopen(request)

            return response.code == 200
        except urllib2.HTTPError, e:
            c_retries += 1

            if c_retries < c_retries_allowed:
                logging.error("Error during archive upload verification attempt %s, trying again" % c_retries)
            else:
                logging.error("Error during archive upload verification final attempt: %s" % e)

            time.sleep(5)

    return False
