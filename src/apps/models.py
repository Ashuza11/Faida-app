from datetime import datetime, date, timezone
from typing import Optional, List
from enum import Enum as PyEnum
from flask_login import UserMixin
from apps import db
from hashlib import md5
from werkzeug.security import generate_password_hash, check_password_hash
import sqlalchemy as sa
import sqlalchemy.orm as so
from decimal import Decimal


# Enum for user roles
class RoleType(PyEnum):
    SUPERADMIN = "superadmin"
    VENDEUR = "vendeur"
    CLIENT = "client"


# Enum for
class CashOutflowCategory(PyEnum):
    PURCHASE_AIRTIME = "Achat Stock"
    OPERATING_EXPENSE = "Frais de Fonctionnement"
    SALARY = "Salaire"
    RENT = "Restoration"
    OTHER = "Autre"


# Enum for
class CashInflowCategory(PyEnum):
    SALE_COLLECTION = "Encaissement Vente"
    OTHER = "Autre Entrée"


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
    # FIX: Use lambda for dynamic default, and timezone.utc for consistency
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # FIX: Use lambda for default and onupdate, and timezone.utc
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    username: so.Mapped[str] = so.mapped_column(
        sa.String(64), index=True, unique=True, nullable=False
    )
    email: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(120), unique=True, nullable=True
    )
    password_hash: so.Mapped[str] = so.mapped_column(
        sa.String(128), nullable=False)
    
    phone: so.Mapped[str] = so.mapped_column(
        sa.String(20), unique=True, nullable=False, index=True
        )
    
    role: so.Mapped[RoleType] = so.mapped_column(
        sa.Enum(RoleType), nullable=False)
    created_by: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    # FIX: Ensure last_login also uses timezone.utc if it's stored dynamically
    last_login: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
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

    cash_inflows_recorded: so.Mapped[list["CashInflow"]] = so.relationship(
        back_populates="recorded_by", foreign_keys="[CashInflow.recorded_by_id]"
    )
    cash_outflows_recorded: so.Mapped[list["CashOutflow"]] = so.relationship(
        back_populates="recorded_by", foreign_keys="[CashOutflow.recorded_by_id]"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role.value})>"

    def avatar(self, size):
        email_or_alt = self.email.lower() if self.email else self.username.lower()
        digest = md5(email_or_alt.encode("utf-8")).hexdigest()
        return f"https://www.gravatar.com/avatar/{digest}?d=identicon&s={size}"


# Client model
class Client(db.Model):
    __tablename__ = "clients"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    # Already correct, but explicitly add timezone=True for consistency with storage
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
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
    balance = db.Column(db.Numeric(precision=10, scale=2),
                        default=0.00, nullable=False)

    buying_price_per_unit: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    selling_price_per_unit: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )

    # Already correct, good!
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
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

    purchased_by_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    purchased_by: so.Mapped["User"] = so.relationship(
        back_populates="stock_purchases_made"
    )

    stock_item_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("stock.id"), nullable=False
    )
    stock_item: so.Mapped["Stock"] = so.relationship(
        back_populates="purchases")

    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )

    buying_price_at_purchase: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(precision=10, scale=2), nullable=False, default=Decimal("0.00")
    )
    selling_price_at_purchase: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(10, 2), nullable=False
    )

    amount_purchased: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False)

    # This was the first created_at, keep this one and ensure lambda and timezone.utc
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<StockPurchase {self.network.value} - {self.amount_purchased} units bought at {self.buying_price_at_purchase} FC, intended sell at {self.selling_price_at_purchase} FC>"


# Sale Model
class Sale(db.Model):
    __tablename__ = "sales"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    # FIX: Use lambda and timezone.utc
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # FIX: Use lambda and timezone.utc
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    vendeur: so.Mapped[User] = so.relationship(back_populates="sales")

    client_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("clients.id"), nullable=True
    )
    client: so.Mapped[Optional[Client]] = so.relationship(
        back_populates="sales")

    client_name_adhoc: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(128), nullable=True
    )

    total_amount_due: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    cash_paid: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    debt_amount: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    sale_items: so.Mapped[List["SaleItem"]] = so.relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )
    cash_inflows: so.Mapped[List["CashInflow"]] = so.relationship(
        back_populates="sale",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        client_info = self.client.name if self.client else self.client_name_adhoc
        return f"<Sale ID:{self.id} to {client_info} by {self.vendeur.username}>"


# New SaleItem Model
class SaleItem(db.Model):
    __tablename__ = "sale_items"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    # FIX: Use lambda and timezone.utc
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    sale_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("sales.id"), nullable=False
    )
    sale: so.Mapped[Sale] = so.relationship(back_populates="sale_items")

    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )
    quantity: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    price_per_unit_applied: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(10, 2), nullable=False
    )
    subtotal: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False
    )

    def __repr__(self) -> str:
        return f"<SaleItem for Sale {self.sale_id}: {self.quantity} units of {self.network.value} at {self.price_per_unit_applied} FC/unit>"


# New Model for Cash Outflows (Sorties)
class CashOutflow(db.Model):
    __tablename__ = "cash_outflows"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    # FIX: Use lambda and timezone.utc
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    recorded_by_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    recorded_by: so.Mapped["User"] = so.relationship(
        back_populates="cash_outflows_recorded"
    )

    amount: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False)
    category: so.Mapped[CashOutflowCategory] = so.mapped_column(
        sa.Enum(CashOutflowCategory), nullable=False
    )
    description: so.Mapped[str] = so.mapped_column(
        sa.String(255), nullable=True)


# Cash Inflows (Entrees - beyond initial sale collection in Sale model)
class CashInflow(db.Model):
    __tablename__ = "cash_inflows"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    # FIX: Use lambda and timezone.utc
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    recorded_by_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    recorded_by: so.Mapped["User"] = so.relationship(
        back_populates="cash_inflows_recorded"
    )

    amount: so.Mapped[sa.Numeric] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False)
    category: so.Mapped[CashInflowCategory] = so.mapped_column(
        sa.Enum(CashInflowCategory),
        nullable=False,
        default=CashInflowCategory.SALE_COLLECTION,
    )
    description: so.Mapped[str] = so.mapped_column(
        sa.String(255), nullable=True)

    sale_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("sales.id"), nullable=True)
    sale: so.Mapped["Sale"] = so.relationship(back_populates="cash_inflows")


# Daily Stock Report Model
class DailyStockReport(db.Model):
    __tablename__ = "daily_stock_reports"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    report_date: so.Mapped[date] = so.mapped_column(
        sa.Date, nullable=False, index=True)
    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )
    initial_stock_balance: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    purchased_stock_amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    sold_stock_amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    final_stock_balance: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    virtual_value: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    debt_amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    __table_args__ = (
        sa.UniqueConstraint("report_date", "network",
                            name="_report_date_network_uc"),
    )

    def __repr__(self) -> str:
        return f"<DailyStockReport {self.report_date} - {self.network.name}>"


# Daily Overall Report Model
class DailyOverallReport(db.Model):
    __tablename__ = "daily_overall_reports"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    report_date: so.Mapped[date] = so.mapped_column(
        sa.Date, unique=True, nullable=False, index=True
    )

    total_initial_stock: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_purchased_stock: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_sold_stock: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_final_stock: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_virtual_value: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_debts: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    def __repr__(self) -> str:
        return f"<DailyOverallReport {self.report_date}>"
