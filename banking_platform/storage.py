from storages.backends.s3boto3 import S3Boto3Storage
from botocore.exceptions import ClientError


class SupabaseS3Storage(S3Boto3Storage):
    """
    Supabase Storage returns 403 (not 404) for non-existent objects.
    Treat 403 as "doesn't exist" so Django can proceed with the upload.
    """

    def exists(self, name):
        try:
            return super().exists(name)
        except ClientError as e:
            if e.response["ResponseMetadata"]["HTTPStatusCode"] == 403:
                return False
            raise
