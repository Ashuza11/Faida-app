from datetime import datetime
from typing import Optional, List
from enum import Enum as PyEnum
from flask_login import UserMixin
from apps import db
from werkzeug.security import generate_password_hash, check_password_hash
import sqlalchemy as sa
import sqlalchemy.orm as so
from decimal import Decimal


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

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    created_at: so.Mapped[datetime] = so.mapped_column(default=datetime.utcnow)
    updated_at: so.Mapped[datetime] = so.mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

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
    stock_purchases_made: so.Mapped[List["StockPurchase"]] = so.relationship(
        back_populates="purchased_by",
        lazy="dynamic",
        cascade="all, delete-orphan",
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

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    created_at: so.Mapped[datetime] = so.mapped_column(default=datetime.utcnow)
    updated_at: so.Mapped[datetime] = so.mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    phone_airtel: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    phone_africel: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    phone_orange: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    phone_vodacom: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    address: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    gps_lat: so.Mapped[Optional[float]] = so.mapped_column()
    gps_long: so.Mapped[Optional[float]] = so.mapped_column()
    is_active: so.Mapped[bool] = so.mapped_column(default=True)
    # Client-specific discount, separate from network's reduction rate
    discount_rate: so.Mapped[sa.Numeric(precision=5, scale=4)] = so.mapped_column(
        sa.Numeric(5, 4), default=0.00
    )

    vendeur_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey("users.id"))
    vendeur: so.Mapped[User] = so.relationship(back_populates="clients")

    sales: so.Mapped[List["Sale"]] = so.relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Client {self.name}>"


# Stock Model
class Stock(db.Model):
    __tablename__ = "stock"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), unique=True, nullable=False
    )
    balance: so.Mapped[int] = so.mapped_column(sa.Integer, default=0, nullable=False)

    selling_price_per_unit: so.Mapped[sa.Numeric(precision=10, scale=2)] = (
        so.mapped_column(sa.Numeric(10, 2), default=1.00, nullable=False)
    )

    reduction_rate: so.Mapped[sa.Numeric(precision=5, scale=4)] = so.mapped_column(
        sa.Numeric(5, 4),
        default=0.00,
        nullable=False,
    )

    updated_at: so.Mapped[datetime] = so.mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    purchases: so.Mapped[List["StockPurchase"]] = so.relationship(
        back_populates="stock_item", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Stock {self.network.value}: {self.balance} units>"


# StockPurchase Model
class StockPurchase(db.Model):
    __tablename__ = "stock_purchases"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    stock_item_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("stock.id"), nullable=False
    )
    stock_item: so.Mapped[Stock] = so.relationship(back_populates="purchases")

    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )
    selling_price_at_purchase: so.Mapped[sa.Numeric(precision=10, scale=2)] = (
        so.mapped_column(sa.Numeric(10, 2), nullable=False)
    )
    amount_purchased: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)

    cost: so.Mapped[Optional[Decimal]] = so.mapped_column(
        sa.Numeric(12, 2), nullable=True
    )

    purchased_by_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    purchased_by: so.Mapped[User] = so.relationship(
        back_populates="stock_purchases_made"
    )

    created_at: so.Mapped[datetime] = so.mapped_column(default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<StockPurchase {self.network.value} - {self.amount_purchased}FC by User {self.purchased_by_id}>"


# New Sale Model
class Sale(db.Model):
    __tablename__ = "sales"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    created_at: so.Mapped[datetime] = so.mapped_column(default=datetime.utcnow)
    updated_at: so.Mapped[datetime] = so.mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    vendeur: so.Mapped[User] = so.relationship(back_populates="sales")

    client_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("clients.id"), nullable=True
    )
    # The client for this sale. Can be null if it's an unregistered (adhoc) client.
    client: so.Mapped[Optional[Client]] = so.relationship(back_populates="sales")

    # If client is not registered, their name can be captured here.
    # This ensures a name is always associated with a sale, even if not a registered client.
    client_name_adhoc: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(128), nullable=True
    )

    # Total amount due for this entire sale (sum of all SaleItems)
    total_amount_due: so.Mapped[sa.Numeric(precision=12, scale=2)] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    # Amount of cash paid by the client
    cash_paid: so.Mapped[sa.Numeric(precision=12, scale=2)] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    # Debt remaining for this sale (total_amount_due - cash_paid)
    debt_amount: so.Mapped[sa.Numeric(precision=12, scale=2)] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    # Relationship to individual SaleItems
    sale_items: so.Mapped[List["SaleItem"]] = so.relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        client_info = self.client.name if self.client else self.client_name_adhoc
        return f"<Sale ID:{self.id} to {client_info} by {self.vendeur.username}>"


# New SaleItem Model (One Sale can have multiple SaleItems for different networks)
class SaleItem(db.Model):
    __tablename__ = "sale_items"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    created_at: so.Mapped[datetime] = so.mapped_column(default=datetime.utcnow)

    sale_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("sales.id"), nullable=False
    )
    sale: so.Mapped[Sale] = so.relationship(back_populates="sale_items")

    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )
    quantity: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False
    )  # Amount of airtime sold for this network

    # Price per unit for this specific sale item (after network reduction)
    # This is effectively the final selling price per unit applied to this quantity
    price_per_unit_applied: so.Mapped[sa.Numeric(precision=10, scale=2)] = (
        so.mapped_column(sa.Numeric(10, 2), nullable=False)
    )

    # The reduction rate applied to this specific sale item
    # This could come from Stock.reduction_rate at the time of sale.
    reduction_rate_applied: so.Mapped[sa.Numeric(precision=5, scale=4)] = (
        so.mapped_column(sa.Numeric(5, 4), nullable=False, default=Decimal("0.00"))
    )

    # Subtotal for this specific SaleItem (quantity * price_per_unit_applied)
    subtotal: so.Mapped[sa.Numeric(precision=12, scale=2)] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False
    )

    def __repr__(self) -> str:
        return f"<SaleItem for Sale {self.sale_id}: {self.quantity} units of {self.network.value} at {self.price_per_unit_applied} FC/unit>"
