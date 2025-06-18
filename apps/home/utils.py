from apps import db
from apps.authentication.models import User, RoleType, NetworkType, Stock
from apps.authentication.util import create_superadmin


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
                    selling_price_per_unit=1.00,  # 28 or 27.5
                    reduction_rate=0.00,
                )
                db.session.add(initial_stock_item)
                app.logger.info(f"Initialized Stock for {network_type.value}")
        db.session.commit()
        app.logger.info("Stock initialization complete.")
