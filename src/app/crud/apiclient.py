from typing import Optional

from sqlalchemy.orm import Session

from app.crud.base import CRUDRepository
from app.models.apiclient import ApiClient
from app.services.cache_service import TTLCache

# ApiClient rows are flat (no relationships) and change rarely, but the same
# api_key is reused across many requests (e.g. shared mobile app key) - cache
# the lookup to avoid a DB round trip, and a pooled connection, on every request.
_api_client_cache = TTLCache(ttl_seconds=60)


class ApiClientCRUDRepository(CRUDRepository):

    @staticmethod
    def is_active_client(client: ApiClient) -> bool:
        """
        Check if an api client is active.

        Parameters:
            client (ApiClient): The api client object to check.

        Returns:
            bool: True if the api client is active, False otherwise.
        """
        return client.is_active

    def get_by_api_key_cached(self, db: Session, api_key: str) -> Optional[ApiClient]:
        """
        Retrieves an api client by its key, cached for a short TTL to absorb
        repeated lookups of the same shared key under heavy traffic.

        Parameters:
            db (Session): The database session.
            api_key (str): The raw api key value.

        Returns:
            Optional[ApiClient]: The matching api client, if found.
        """
        def fetch() -> Optional[ApiClient]:
            client = self.get_one(db, ApiClient.api_key == api_key)
            if client is not None:
                # Detach immediately so a later commit on this session (e.g. from
                # some other write request reusing the same api_key) can't expire
                # this object's attributes while it sits in the cache.
                db.expunge(client)
            return client

        return _api_client_cache.get_or_set(api_key, fetch)


apiclient_crud = ApiClientCRUDRepository(model=ApiClient)
