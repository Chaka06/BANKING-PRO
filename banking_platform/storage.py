import os
import mimetypes
import requests
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class SupabaseStorage(Storage):
    """
    Django storage backend using Supabase Storage REST API.
    Requires SUPABASE_URL and SUPABASE_SERVICE_KEY env vars.
    Avoids S3-compatible API entirely (no boto3, no S3 credentials).
    """

    def __init__(self):
        self._url = os.environ.get('SUPABASE_URL', '')
        self._key = os.environ.get('SUPABASE_SERVICE_KEY', '')
        self._bucket = os.environ.get('STORAGE_BUCKET_NAME', 'media')

    def _base(self):
        return f"{self._url}/storage/v1"

    def _auth(self, content_type='application/octet-stream'):
        return {
            'Authorization': f'Bearer {self._key}',
            'Content-Type': content_type,
            'x-upsert': 'true',
        }

    def _save(self, name, content):
        content_type, _ = mimetypes.guess_type(name)
        if not content_type:
            content_type = 'application/octet-stream'
        data = content.read() if hasattr(content, 'read') else content
        resp = requests.post(
            f"{self._base()}/object/{self._bucket}/{name}",
            headers=self._auth(content_type),
            data=data,
        )
        if resp.status_code not in (200, 201):
            raise Exception(f"Supabase upload failed [{resp.status_code}]: {resp.text}")
        return name

    def exists(self, name):
        resp = requests.head(
            f"{self._base()}/object/{self._bucket}/{name}",
            headers={'Authorization': f'Bearer {self._key}'},
        )
        return resp.status_code == 200

    def url(self, name):
        return f"{self._url}/storage/v1/object/public/{self._bucket}/{name}"

    def _open(self, name, mode='rb'):
        resp = requests.get(
            f"{self._base()}/object/{self._bucket}/{name}",
            headers={'Authorization': f'Bearer {self._key}'},
        )
        if resp.status_code != 200:
            raise FileNotFoundError(f"Supabase: {name} introuvable ({resp.status_code})")
        from django.core.files.base import ContentFile
        return ContentFile(resp.content, name=name)

    def delete(self, name):
        requests.delete(
            f"{self._base()}/object/{self._bucket}/{name}",
            headers={'Authorization': f'Bearer {self._key}'},
        )

    def size(self, name):
        resp = requests.head(
            f"{self._base()}/object/{self._bucket}/{name}",
            headers={'Authorization': f'Bearer {self._key}'},
        )
        if resp.status_code == 200:
            return int(resp.headers.get('content-length', 0))
        return 0

    def path(self, name):
        raise NotImplementedError("SupabaseStorage does not support local file paths.")
