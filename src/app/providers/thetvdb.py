import logging

import requests
from django.conf import settings
from django.core.cache import cache

import json
from app import helpers
from app.models import MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)
base_url = "https://api4.thetvdb.com/v4"

base_params = {
    "language": settings.THETVDB_LANG,
}

def _get_token():
    """Get the API token for TheTVDB."""
    data = json.dumps({
        "apikey": settings.THE_TVDB_API,
    }, indent=2).encode("utf-8")

    try:
        response = requests.get(
            f"{base_url}/login", 
            data=data, 
            headers={
                "Content-Type": "application/json",
            }
        )

        data_response = json.loads(response.text)
    except requests.exceptions.HTTPError as error:
        handle_error(error)

    return data_response["data"]["token"]

def handle_error(error):
    """Handle TheTVDB API errors."""
    error_resp = error.response
    status_code = error_resp.status_code

    try:
        error_json = error_resp.json()
    except requests.exceptions.JSONDecodeError as json_error:
        logger.exception("Failed to decode JSON response")
        raise services.ProviderAPIError(Sources.TMDB.value, error) from json_error

    # Handle authentication errors
    if status_code == requests.codes.unauthorized:
        details = error_json.get("status_message")
        if details:
            # Remove trailing period if present
            details = details.rstrip(".")
            raise services.ProviderAPIError(Sources.TMDB.value, error, details)

    raise services.ProviderAPIError(
        Sources.THETVDB.value,
        error,
    )

def search(media_type, query, page):
    """Search for media on TheTVDB."""
    cache_key = f"search_{Sources.THETVDB.value}_{media_type}_{query}_{page}"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/search"

        params = {
            **base_params,
            "query": query,
            "page": page,
            "type": media_type,
        }

        try:
            response = services.api_request(
                Sources.THETVDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        results = [
            {
                "media_id": media["id"],
                "source": Sources.THETVDB.value,
                "media_type": media_type,
                "title": get_title(media),
                "image": get_image_url(media["image_url"]),
            }
            for media in response["data"]
        ]


def get_image_url(path):
    """Return the image URL for the media."""
    # when no image, value from response is null
    # e.g https://www.thetvdb.com/series/star-wars-1x1-a-batalha-dos-fas
    if path:
        return path
    return settings.IMG_NONE_THETVDB

def get_title(response):
    """Return the title for the media."""
    try:
        return response["name_translated"]
    except KeyError:
        return response["name"]