import unittest

from pydantic import ValidationError

from app.schemas.restaurant import RestaurantBase


class RestaurantAccessibilityTests(unittest.TestCase):
    def restaurant(self, **fields):
        return RestaurantBase(**{
            "name": "Chez Tofu", "latitude": 48.85, "longitude": 2.35,
            "vegan_status": "FULLY_VEGAN", "tags": ["restaurant"], **fields,
        })

    def test_unknown_by_default(self):
        restaurant = self.restaurant()
        self.assertIsNone(restaurant.entrance_access)
        self.assertIsNone(restaurant.has_toilets)
        self.assertIsNone(restaurant.has_accessible_toilets)

    def test_accessible_toilets_imply_toilets(self):
        restaurant = self.restaurant(has_accessible_toilets=True)
        self.assertTrue(restaurant.has_toilets)

    def test_accessible_toilets_without_toilets_is_refused(self):
        with self.assertRaises(ValidationError):
            self.restaurant(has_toilets=False, has_accessible_toilets=True)

    def test_unknown_entrance_access_is_refused(self):
        with self.assertRaises(ValidationError):
            self.restaurant(entrance_access="elevator")

    def test_cleared_without_storefront(self):
        restaurant = self.restaurant(
            tags=["caterer"], has_storefront=False, service_area="Paris",
            phone="0102030405", entrance_access="step_free",
            has_toilets=True, has_accessible_toilets=True,
            accessibility_note="Porte étroite",
        )
        self.assertIsNone(restaurant.entrance_access)
        self.assertIsNone(restaurant.has_toilets)
        self.assertIsNone(restaurant.has_accessible_toilets)
        self.assertIsNone(restaurant.accessibility_note)


if __name__ == "__main__":
    unittest.main()
