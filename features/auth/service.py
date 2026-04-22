from __future__ import annotations

from fastapi import Depends

from features.core.dependencies import get_auth_service
from features.shared.services.auth_service import AuthService


class AuthModuleService:
    def __init__(self, auth: AuthService) -> None:
        self._auth = auth

    def login(self, identifier: str, password: str, role: str) -> dict:
        return self._auth.login(identifier, password, role)

    def change_password(self, current_user: dict, current_password: str, new_password: str) -> None:
        self._auth.change_password(current_user, current_password, new_password)


def get_auth_module(auth: AuthService = Depends(get_auth_service)) -> AuthModuleService:
    return AuthModuleService(auth)
