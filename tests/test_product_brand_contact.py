"""Tests for the `brand_contact` filter of the product search."""
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.crud import product_crud
from app.crud.product import brand_contact_clause
from app.database.base_class import Base
from app.models import Brand, Checking, InterestingProduct, Product, ProductCategory, User


def _levenshtein(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


class BrandContactFilterTestCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.addCleanup(engine.dispose)

        @event.listens_for(engine, "connect")
        def _register_postgres_functions(dbapi_connection, _):
            # Used by the ranked brand search, which only exists in PostgreSQL
            dbapi_connection.create_function("levenshtein", 2, _levenshtein)
            dbapi_connection.create_function("greatest", 2, max)

        with engine.begin() as connection:
            Base.metadata.create_all(connection, tables=[
                User.__table__, Brand.__table__, ProductCategory.__table__,
                InterestingProduct.__table__, Product.__table__, Checking.__table__,
            ])
        self.db = Session(engine)
        self.addCleanup(self.db.close)

        # Hierarchy: Group (email) > Subsidiary (nothing) > Label (nothing)
        group = Brand(name="Group", email="contact@group.test")
        subsidiary = Brand(name="Subsidiary", parent=group)
        label = Brand(name="Label", parent=subsidiary)
        form_only = Brand(name="Form Only", contact_form_url="https://form.test")
        both = Brand(name="Both", email="hello@both.test", contact_form_url="https://both.test")
        empty_email = Brand(name="Empty Email", email="")
        unreachable = Brand(name="Unreachable")
        self.db.add_all([group, subsidiary, label, form_only, both, empty_email, unreachable])
        self.db.flush()

        for ean, brand in [
            ("1", group), ("2", label), ("3", form_only), ("4", both),
            ("5", empty_email), ("6", unreachable), ("7", None),
        ]:
            self.db.add(Product(ean=ean, name=f"Product {ean}", brand=brand))
        self.db.commit()

    def search(self, contact, **filters):
        products, total = product_crud.get_many(
            self.db, limit=100, order_by="ean", clauses=[brand_contact_clause(contact)], **filters,
        )
        eans = [product.ean for product in products]
        self.assertEqual(total, len(eans))
        return eans

    def test_email_includes_inherited_email(self):
        self.assertEqual(self.search("email"), ["1", "2", "4"])

    def test_form(self):
        self.assertEqual(self.search("form"), ["3", "4"])

    def test_none_includes_products_without_brand(self):
        self.assertEqual(self.search("none"), ["5", "6", "7"])

    def test_combines_with_other_filters(self):
        self.assertEqual(self.search("email", ean__ne="1"), ["2", "4"])

    def test_paginated_total_counts_all_matches(self):
        products, total = product_crud.get_many(
            self.db, limit=1, order_by="ean", clauses=[brand_contact_clause("email")],
        )
        self.assertEqual([product.ean for product in products], ["1"])
        self.assertEqual(total, 3)

    def test_ranked_brand_search(self):
        products, total = product_crud.get_many_ranked(
            self.db, "brand___name", "label", limit=100, clauses=[brand_contact_clause("email")],
        )
        self.assertEqual([product.ean for product in products], ["2"])
        self.assertEqual(total, 1)

        products, total = product_crud.get_many_ranked(
            self.db, "brand___name", "label", limit=100, clauses=[brand_contact_clause("none")],
        )
        self.assertEqual((products, total), ([], 0))

    def test_unknown_value(self):
        with self.assertRaises(ValueError):
            brand_contact_clause("phone")


if __name__ == "__main__":
    unittest.main()
