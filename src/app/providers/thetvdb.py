import logging

import requests
from django.conf import settings
from django.core.cache import cache

import json
import jwt
from app import helpers
from app.models import MediaTypes, Sources
from app.providers import services
from langcodes import Language
from time import time
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)
base_url = "https://api4.thetvdb.com/v4"

base_params = {
    "language": settings.THETVDB_LANG,
}

TYPES = {
    MediaTypes.MOVIE.value: "movie",
    MediaTypes.TV.value: "series",
    MediaTypes.ANIME.value: "series",
}

def _is_token_expired(token):
    """Check if the JWT token is expired."""
    if not token:
        return True
    
    try:
        # Decode the JWT token without verification to check expiration
        decoded = jwt.decode(token, options={"verify_signature": False})
        exp = decoded.get('exp')
        
        if exp is None:
            return True
            
        # Check if token is expired (with a 5-minute buffer)
        current_time = time()
        return current_time >= (exp - 300)  # 300 seconds = 5 minutes buffer
        
    except jwt.DecodeError:
        logger.error("Failed to decode JWT token")
        return True
    except Exception as e:
        logger.error(f"Error checking token expiration: {e}")
        return True

def _get_token():
    """Get the API token for TheTVDB."""
    cache_key = "thetvdb_token"
    token = cache.get(cache_key)
    if token is None or _is_token_expired(token):
        data = json.dumps({
            "apikey": settings.THETVDB_API,
        }, indent=2).encode("utf-8")

        try:
            response = requests.post(
                f"{base_url}/login", 
                data=data, 
                headers={
                    "Content-Type": "application/json",
                }
            )

            data_response = json.loads(response.text)
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        token = data_response["data"]["token"]
        cache.set("thetvdb_token", token, 60 * 60 * 24 * 30)  # Cache for 30 days

    return token

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

    if page >= 1:
        corrected_page = page - 1 # TheTVDB starts pages at 0
    else:
        corrected_page = page
    
    cache_key = f"search_{Sources.THETVDB.value}_{media_type}_{query}_{page}"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/search"

        params = {
            "query": quote_plus(query),
            "page": corrected_page,
            "type": TYPES[media_type],
            **base_params,
        }

        try:
            # Get the API token
            token = _get_token()
            
            response = services.api_request(
                Sources.THETVDB.value,
                "GET",
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                }
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        results = [
            {
                "media_id": media["id"],
                "source": Sources.THETVDB.value,
                "media_type": media_type,
                "title": get_title(media, settings.THETVDB_LANG),
                "image": get_image_url(media["image_url"]),
            }
            for media in response["data"]
        ]

        total_results = response["links"]["total_items"]
        per_page = response["links"]["page_size"]
        data = helpers.format_search_response(
            page,
            per_page,
            total_results,
            results,
        )

        cache.set(cache_key, data)

    return data


def get_image_url(path):
    """Return the image URL for the media."""
    # when no image, value from response is null
    # e.g https://www.thetvdb.com/series/star-wars-1x1-a-batalha-dos-fas
    if path:
        return path
    return settings.IMG_NONE_THETVDB

def get_title(response, language=None):
    """Return the title for the media."""
    # convert language to alpha-3 code
    # for example, 'en' becomes 'eng'
    if language is not None:
        lang = Language.get(language).to_alpha3()
        return response["translations"].get(lang, response["name"])
    
    return response["name"]