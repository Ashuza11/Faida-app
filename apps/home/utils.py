from apps import db
from apps.authentication.models import NetworkType, Stock

from decimal import Decimal, ROUND_UP, getcontext


def initialize_stock_items(app):
    """
    Initializes default stock entries for each network type if they don't exist.
    """
    with app.app_context():
        for network_type in NetworkType:
            if not Stock.query.filter_by(network=network_type).first():
                initial_stock_item = Stock(
                    network=network_type,
                    balance=0,
                    buying_price=27.1,  # 27.1 >
                )
                db.session.add(initial_stock_item)
                app.logger.info(f"Initialized Stock for {network_type.value}")
        db.session.commit()
        app.logger.info("Stock initialization complete.")


# Set precision for Decimal operations
getcontext().prec = 10


def custom_round_up(amount: Decimal) -> Decimal:
    """
    Rounds a Decimal amount based on its last two digits for whole numbers (FC).

    Examples:
    - 6924.00 -> 6900.00 (xx.01 to xx.24 rounds down to xx.00)
    - 6925.00 -> 6950.00 (xx.25 to xx.49 rounds up to xx.50)
    - 6949.00 -> 6950.00
    - 6950.00 -> 6950.00 (remains xx.50)
    - 6951.00 -> 7000.00 (xx.51 to xx.99 rounds up to xx.100)
    - 6975.00 -> 7000.00
    - 6999.00 -> 7000.00
    - 6900.00 -> 6900.00 (xx.00 remains xx.00)
    """
    # Ensure amount is a Decimal
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))

    # Calculate the remainder when divided by 100
    remainder = amount % 100

    if remainder == Decimal("0"):
        return amount  # xx.00 remains xx.00
    elif Decimal("1") <= remainder <= Decimal("24"):
        # xx.01 to xx.24 rounds DOWN to xx.00
        return amount - remainder
    elif Decimal("25") <= remainder <= Decimal("50"):
        # xx.25 to xx.50 rounds UP to xx.50
        return (amount - remainder) + Decimal("50")
    elif Decimal("51") <= remainder <= Decimal("99"):
        # xx.51 to xx.99 rounds UP to xx.100 (next whole hundred)
        return (amount - remainder) + Decimal("100")
    else:
        # This case should ideally not be reached if remainder is always 0-99
        return amount
