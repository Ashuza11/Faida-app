from datetime import datetime
from typing import Optional, List
from enum import Enum as PyEnum
from flask_login import UserMixin
from apps import db
from werkzeug.security import generate_password_hash, check_password_hash
import sqlalchemy as sa
import sqlalchemy.orm as so


# Enum for user roles
class RoleType(PyEnum):
    SUPERADMIN = "superadmin"
    VENDEUR = "vendeur"
    CLIENT = "client"


# Enum for network operators
class NetworkType(PyEnum):
    AIRTEL = "airtel"
    AFRICEL = "africel"
    ORANGE = "orange"
    VODACOM = "vodacom"


# User model
class User(db.Model, UserMixin):
    __tablename__ = "users"

    # Common fields that were in Base
    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    created_at: so.Mapped[datetime] = so.mapped_column(default=datetime.utcnow)
    updated_at: so.Mapped[datetime] = so.mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # User-specific fields
    username: so.Mapped[str] = so.mapped_column(
        sa.String(64), index=True, unique=True, nullable=False
    )
    email: so.Mapped[str] = so.mapped_column(
        sa.String(120), unique=True, nullable=False
    )
    password_hash: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(128), nullable=False
    )
    phone: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20), unique=True)
    role: so.Mapped[RoleType] = so.mapped_column(sa.Enum(RoleType), nullable=False)
    created_by: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    last_login: so.Mapped[Optional[datetime]] = so.mapped_column(nullable=True)
    is_active: so.Mapped[bool] = so.mapped_column(default=True)

    # Relationships
    creator = so.relationship(
        "User",
        remote_side=[id],
        backref=so.backref("created_users", lazy="dynamic"),
    )
    clients: so.Mapped[List["Client"]] = so.relationship(
        back_populates="vendeur", cascade="all, delete-orphan"
    )
    sales: so.Mapped[List["Sale"]] = so.relationship(
        back_populates="vendeur", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role.value})>"


# Client model
class Client(db.Model):
    __tablename__ = "clients"

    # Common fields
    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    created_at: so.Mapped[datetime] = so.mapped_column(default=datetime.utcnow)
    updated_at: so.Mapped[datetime] = so.mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Client-specific fields
    name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    phone_airtel: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    phone_africel: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    phone_orange: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    phone_vodacom: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    address: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    gps_lat: so.Mapped[Optional[float]] = so.mapped_column()
    gps_long: so.Mapped[Optional[float]] = so.mapped_column()
    is_active: so.Mapped[bool] = so.mapped_column(default=True)
    discount_rate: so.Mapped[Optional[float]] = so.mapped_column(default=0.0)

    vendeur_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey("users.id"))
    vendeur: so.Mapped[User] = so.relationship(back_populates="clients")

    sales: so.Mapped[List["Sale"]] = so.relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Client {self.name}>"


class Sale(db.Model):
    __tablename__ = "sales"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    created_at: so.Mapped[datetime] = so.mapped_column(default=datetime.utcnow)
    updated_at: so.Mapped[datetime] = so.mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Foreign Keys
    vendeur_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey("users.id"))
    client_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey("clients.id"))

    # Relationships
    vendeur: so.Mapped[User] = so.relationship(back_populates="sales")
    client: so.Mapped[Client] = so.relationship(back_populates="sales")

    # Example Sale fields (adjust to your real use case)
    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )
    quantity: so.Mapped[float] = so.mapped_column(nullable=False)
    total_price: so.Mapped[float] = so.mapped_column(nullable=False)

    def __repr__(self) -> str:
        return f"<Sale to {self.client.name} by {self.vendeur.username}>"
