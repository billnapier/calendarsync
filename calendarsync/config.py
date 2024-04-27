"""Application Configuation Wrapper"""


from google.cloud import secretmanager

class Config:
    """Contains configuration settings for the application."""
    def __init__(self):
        self._secret_manager = secretmanager.SecretManagerServiceClient()
        self.project = 'calendarsync-420905'
        self.sqlalchemy_database_uri = 'bigquery://' + self.project + '/calendarsync_prod'

    def access_secret(self, secret_name: str):
        """Get the named secret from the secret manager."""
        name = self._secret_manager.secret_version_path(self.project, secret_name, 'latest')
        response = self._secret_manager.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")

    