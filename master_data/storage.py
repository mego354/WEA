"""
Cloudflare R2 S3-compatible Django Storage Backend.
Reads configuration exclusively from Django settings (populated from environment variables).
Never logs or exposes credentials.
"""

import io
import logging
from urllib.parse import urljoin

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


@deconstructible
class CloudflareR2Storage(Storage):
    """Django Storage backend for Cloudflare R2 using boto3 S3v4."""

    def __init__(self):
        self.bucket_name = getattr(settings, 'CLOUDFLARE_R2_BUCKET_NAME', '')
        self.endpoint_url = getattr(settings, 'CLOUDFLARE_R2_ENDPOINT_URL', '')
        self.custom_domain = getattr(settings, 'CLOUDFLARE_R2_CUSTOM_DOMAIN', '').rstrip('/')
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=getattr(settings, 'CLOUDFLARE_R2_ACCESS_KEY', ''),
                aws_secret_access_key=getattr(settings, 'CLOUDFLARE_R2_SECRET_KEY', ''),
                region_name='auto',
                config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
            )
        return self._client

    def _normalize_name(self, name):
        cleaned = str(name or '').lstrip('/').replace('\\', '/')
        parts = [p for p in cleaned.split('/') if p]
        if any(p == '..' for p in parts):
            raise ValueError("Invalid storage key containing path traversal segment.")
        return '/'.join(parts)

    def _open(self, name, mode='rb'):
        key = self._normalize_name(name)
        resp = self.client.get_object(Bucket=self.bucket_name, Key=key)
        data = resp['Body'].read()
        return ContentFile(data, name=key)

    def _save(self, name, content):
        key = self._normalize_name(name)
        if hasattr(content, 'seek'):
            content.seek(0)
        body = content.read()
        content_type = getattr(content, 'content_type', None)
        if not content_type:
            import mimetypes
            content_type, _ = mimetypes.guess_type(key)
        extra_args = {'ContentType': content_type or 'application/octet-stream'}
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=body,
            **extra_args,
        )
        return key

    def delete(self, name):
        key = self._normalize_name(name)
        if not key:
            return
        self.client.delete_object(Bucket=self.bucket_name, Key=key)

    def exists(self, name):
        key = self._normalize_name(name)
        if not key:
            return False
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except Exception:
            return False

    def size(self, name):
        key = self._normalize_name(name)
        resp = self.client.head_object(Bucket=self.bucket_name, Key=key)
        return int(resp.get('ContentLength', 0))

    def url(self, name, expires_in=300, force_presigned=False):
        key = self._normalize_name(name)
        if self.custom_domain and not force_presigned:
            base = self.custom_domain if self.custom_domain.startswith(('http://', 'https://')) else f'https://{self.custom_domain}'
            return urljoin(f'{base}/', key)
        return self.client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket_name, 'Key': key},
            ExpiresIn=expires_in,
        )
