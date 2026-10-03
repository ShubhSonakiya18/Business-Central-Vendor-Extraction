from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database.db import get_db
from app.services.auth_services.security import decode_token
from app.models.model import User

# `description` is documentation only (shown in Swagger's Authorize popup); token
# extraction and validation are unchanged. See app/swagger_ui.py.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="auth/login",
    description=(
        "Sign in with your application account: enter your **email** in the "
        "*username* box and your password. Leave client_id and client_secret blank."
    ),
)

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise credentials_exception

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise credentials_exception

    return user