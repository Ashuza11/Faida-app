import pytest

from apps.businesses import create_business
from apps.client_identities import (
    ClientIdentityError,
    ensure_unique_client_name,
    replace_client_phones,
    resolve_sms_sale_client,
)
from apps.models import (
    BusinessType,
    Client,
    ClientPhone,
    ClientPhoneConflict,
    NetworkType,
    RoleType,
    User,
)


def make_owner_and_business(session, suffix="1", business_type=BusinessType.RETAIL):
    owner = User(
        username=f"owner-{suffix}",
        phone=f"+24381000001{suffix}",
        role=RoleType.VENDEUR,
    )
    owner.set_password("safe-password")
    session.add(owner)
    session.flush()
    business = create_business(
        owner=owner, name=f"Business {suffix}", business_type=business_type
    )
    session.flush()
    return owner, business


def test_one_client_can_own_many_numbers_across_and_within_networks(session):
    owner, business = make_owner_and_business(session)
    client = Client(name="Deric Centre", vendeur_id=owner.id, business_id=business.id)
    session.add(client)
    session.flush()

    replace_client_phones(client=client, phone_entries=[
        (NetworkType.AIRTEL, "0972 067 057"),
        (NetworkType.AIRTEL, "+243 991 234 567"),
        (NetworkType.ORANGE, "0841-234-567"),
    ])
    session.flush()

    assert {(phone.network, phone.normalized_phone) for phone in client.phones} == {
        (NetworkType.AIRTEL, "+243972067057"),
        (NetworkType.AIRTEL, "+243991234567"),
        (NetworkType.ORANGE, "+243841234567"),
    }


def test_sms_numbers_resolve_to_the_same_client(session):
    owner, business = make_owner_and_business(session)
    client = Client(name="Deric Centre", vendeur_id=owner.id, business_id=business.id)
    session.add(client)
    session.flush()
    replace_client_phones(client=client, phone_entries=[
        (NetworkType.AIRTEL, "0972067057"),
        (NetworkType.ORANGE, "0841234567"),
    ])
    session.flush()

    airtel_client, airtel_created = resolve_sms_sale_client(
        business=business,
        owner=owner,
        network=NetworkType.AIRTEL,
        raw_phone="243972067057",
    )
    orange_client, orange_created = resolve_sms_sale_client(
        business=business,
        owner=owner,
        network=NetworkType.ORANGE,
        raw_phone="0841234567",
    )

    assert airtel_client.id == orange_client.id == client.id
    assert not airtel_created
    assert not orange_created


def test_unknown_number_reuses_automatically_discovered_client(session):
    owner, business = make_owner_and_business(session)

    first, first_created = resolve_sms_sale_client(
        business=business, owner=owner, network=NetworkType.AIRTEL,
        raw_phone="0972067057",
    )
    session.flush()
    second, second_created = resolve_sms_sale_client(
        business=business, owner=owner, network=NetworkType.AIRTEL,
        raw_phone="+243972067057",
    )

    assert first.id == second.id
    assert first.registration_source == "sms"
    assert first.identification_status == "needs_name"
    assert first_created
    assert not second_created


def test_phone_identity_is_isolated_between_businesses(session):
    owner_one, business_one = make_owner_and_business(session, "1")
    owner_two, business_two = make_owner_and_business(session, "2")

    first, _ = resolve_sms_sale_client(
        business=business_one, owner=owner_one, network=NetworkType.AIRTEL,
        raw_phone="0972067057",
    )
    second, _ = resolve_sms_sale_client(
        business=business_two, owner=owner_two, network=NetworkType.AIRTEL,
        raw_phone="0972067057",
    )

    assert first.id != second.id
    assert ClientPhone.query.count() == 2


def test_duplicate_phone_cannot_be_assigned_to_another_client(session):
    owner, business = make_owner_and_business(session)
    first = Client(name="Deric Centre", vendeur_id=owner.id, business_id=business.id)
    second = Client(name="Deric Route", vendeur_id=owner.id, business_id=business.id)
    session.add_all([first, second])
    session.flush()
    replace_client_phones(
        client=first, phone_entries=[(NetworkType.AIRTEL, "0972067057")]
    )
    session.flush()

    with pytest.raises(ClientIdentityError, match="Deric Centre"):
        replace_client_phones(
            client=second, phone_entries=[(NetworkType.AIRTEL, "+243972067057")]
        )


def test_active_clients_need_distinct_names_within_one_business(session):
    owner, business = make_owner_and_business(session)
    existing = Client(name="Deric", vendeur_id=owner.id, business_id=business.id)
    session.add(existing)
    session.flush()

    with pytest.raises(ClientIdentityError, match="distinguer"):
        ensure_unique_client_name(business_id=business.id, name=" deric ")

    assert ensure_unique_client_name(
        business_id=business.id, name="Deric Marché"
    ) == "Deric Marché"


def test_ambiguous_legacy_number_blocks_sms_until_owner_resolves_it(session):
    owner, business = make_owner_and_business(session)
    first = Client(name="Deric Centre", vendeur_id=owner.id, business_id=business.id)
    second = Client(name="Deric Route", vendeur_id=owner.id, business_id=business.id)
    session.add_all([first, second])
    session.flush()
    for client in (first, second):
        session.add(ClientPhoneConflict(
            business_id=business.id,
            client_id=client.id,
            network=NetworkType.AIRTEL,
            normalized_phone="+243972067057",
        ))
    session.flush()

    with pytest.raises(ClientIdentityError, match="plusieurs clients"):
        resolve_sms_sale_client(
            business=business,
            owner=owner,
            network=NetworkType.AIRTEL,
            raw_phone="0972067057",
        )

    replace_client_phones(
        client=first, phone_entries=[(NetworkType.AIRTEL, "0972067057")]
    )
    session.flush()
    resolved, created = resolve_sms_sale_client(
        business=business,
        owner=owner,
        network=NetworkType.AIRTEL,
        raw_phone="0972067057",
    )
    assert resolved.id == first.id
    assert not created
