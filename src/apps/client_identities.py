"""Business-scoped client names and phone identities for automatic sale capture."""

from collections import defaultdict

from sqlalchemy import func

from apps import db
from apps.models import (
    Client,
    ClientPhone,
    ClientPhoneConflict,
    NetworkType,
    normalize_phone,
    validate_drc_phone,
)


class ClientIdentityError(ValueError):
    """Raised when a client name or phone identity would be ambiguous."""


def normalized_client_name(name: str) -> str:
    return " ".join((name or "").split()).strip()


def ensure_unique_client_name(*, business_id: int, name: str, exclude_client_id=None):
    clean_name = normalized_client_name(name)
    if len(clean_name) < 2:
        raise ClientIdentityError("Le nom du client doit contenir au moins 2 caractères.")
    query = Client.query.filter(
        Client.business_id == business_id,
        Client.is_active.is_(True),
        func.lower(Client.name) == clean_name.casefold(),
    )
    if exclude_client_id is not None:
        query = query.filter(Client.id != exclude_client_id)
    if query.first() is not None:
        raise ClientIdentityError(
            "Ce nom est déjà utilisé. Ajoutez un détail pour distinguer les deux clients."
        )
    return clean_name


def normalize_client_phone(raw_phone: str) -> str:
    normalized = normalize_phone(raw_phone)
    if not validate_drc_phone(normalized):
        raise ClientIdentityError("Numéro congolais invalide.")
    return normalized


def replace_client_phones(*, client: Client, phone_entries):
    """Replace a client's numbers after validating ownership within its business."""
    if client.business_id is None:
        raise ClientIdentityError("Le client doit appartenir à un mode avant d'ajouter un numéro.")

    requested = []
    seen = set()
    for network, raw_phone in phone_entries:
        if not raw_phone:
            continue
        if not isinstance(network, NetworkType):
            network = NetworkType(network)
        normalized = normalize_client_phone(raw_phone)
        key = (network, normalized)
        if key in seen:
            continue
        seen.add(key)
        requested.append(key)

    for network, normalized in requested:
        conflict = ClientPhone.query.filter(
            ClientPhone.business_id == client.business_id,
            ClientPhone.network == network,
            ClientPhone.normalized_phone == normalized,
            ClientPhone.client_id != client.id,
        ).first()
        if conflict is not None:
            raise ClientIdentityError(
                f"Le numéro {normalized} est déjà attribué à {conflict.client.name}."
            )

    for network, normalized in requested:
        ClientPhoneConflict.query.filter_by(
            business_id=client.business_id,
            network=network,
            normalized_phone=normalized,
        ).delete(synchronize_session=False)

    requested_keys = set(requested)
    existing_by_key = {
        (phone.network, phone.normalized_phone): phone for phone in client.phones
    }
    for key, phone in existing_by_key.items():
        if key not in requested_keys:
            db.session.delete(phone)
    # Delete removed identities before inserting replacements so the database
    # uniqueness constraint is respected during edits.
    db.session.flush()
    for network, normalized in requested:
        existing = existing_by_key.get((network, normalized))
        if existing is not None:
            existing.is_active = True
        else:
            client.phones.append(ClientPhone(
                business_id=client.business_id,
                network=network,
                normalized_phone=normalized,
            ))

    # Keep legacy single-number fields synchronized until their later removal.
    grouped = defaultdict(list)
    for network, normalized in requested:
        grouped[network].append(normalized)
    client.phone_airtel = next(iter(grouped[NetworkType.AIRTEL]), None)
    client.phone_africel = next(iter(grouped[NetworkType.AFRICEL]), None)
    client.phone_orange = next(iter(grouped[NetworkType.ORANGE]), None)
    client.phone_vodacom = next(iter(grouped[NetworkType.VODACOM]), None)


def resolve_sms_sale_client(*, business, owner, network, raw_phone, sms_name=None):
    """Resolve or create the stable client identity for one captured sale."""
    normalized = normalize_client_phone(raw_phone)
    legacy_conflicts = ClientPhoneConflict.query.filter_by(
        business_id=business.id,
        network=network,
        normalized_phone=normalized,
    ).count()
    if legacy_conflicts:
        raise ClientIdentityError(
            f"Le numéro {normalized} est attribué à plusieurs clients. Corrigez-le dans Clients."
        )
    identity = ClientPhone.query.filter_by(
        business_id=business.id,
        network=network,
        normalized_phone=normalized,
    ).first()
    if identity is not None:
        if not identity.is_active or not identity.client.is_active:
            raise ClientIdentityError(
                f"Le numéro {normalized} appartient à un client archivé."
            )
        return identity.client, False

    proposed_name = normalized_client_name(sms_name)
    if not proposed_name:
        proposed_name = f"Client à identifier · {normalized}"
    # A network-provided name can collide; retain the phone to keep both people distinct.
    if Client.query.filter(
        Client.business_id == business.id,
        func.lower(Client.name) == proposed_name.casefold(),
    ).first() is not None:
        proposed_name = f"{proposed_name} · {normalized}"

    client = Client(
        name=proposed_name,
        vendeur_id=owner.id,
        business_id=business.id,
        registration_source="sms",
        identification_status="needs_name",
    )
    db.session.add(client)
    db.session.flush()
    replace_client_phones(client=client, phone_entries=[(network, normalized)])
    return client, True
