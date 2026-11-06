from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Text, select, func, case
from sqlalchemy.orm import relationship, object_session
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime
from typing import List, Optional, Dict, Any
from app.database.base_class import Base
from app.models.scoring import BrandCriterionScore, Criterion


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    name = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, nullable=True)
    contact_form_url = Column(String, nullable=True)
    logo_path = Column(String, nullable=True)
    boycott = Column(Boolean, default=False, nullable=True)
    background = Column(Text)
    parent_id = Column(Integer, ForeignKey("brands.id"), nullable=True)
    parent = relationship("Brand", back_populates="children", remote_side=[id])
    children = relationship("Brand", back_populates="parent")
    products = relationship("Product", back_populates="brand")
    interesting_products = relationship(
        "InterestingProduct", back_populates="brand")
    criterion_scores = relationship(
        "BrandCriterionScore", back_populates="brand")

    @property
    def root_email(self) -> str | None:
        if self.email is None and self.parent:
            return self.parent.root_email
        return self.email

    @property
    def root_contact_form_url(self) -> str | None:
        if self.contact_form_url is None and self.parent:
            return self.parent.root_contact_form_url
        return self.contact_form_url

    @property
    def parent_name_tree(self) -> list:
        if self.parent:
            return [self.name] + self.parent.parent_name_tree
        return [self.name]

    @property
    def root_brand(self):
        """Get the root brand in the hierarchy."""
        if self.parent:
            return self.parent.root_brand
        return self

    @hybrid_property
    def parent_name(self):
        if self.parent:
            return self.parent.name
        return None

    @parent_name.inplace.expression
    @classmethod
    def _parent_name_expression(cls):
        return Brand.parent

    @hybrid_property
    def score(self):
        """
        Calculate the average score for this brand.
        If the brand doesn't have its own scores but has a parent/ancestor with scores,
        use the root brand's score.
        """
        if hasattr(self, '_score_cache'):
            return self._score_cache

        # First try to calculate the brand's own score
        if len(self.criterion_scores) > 0:
            max_total_point = object_session(self).query(Criterion).count() * 5
            if max_total_point > 0:
                total_score = sum(
                    score.score for score in self.criterion_scores)
                avg_score = (total_score * 100) / max_total_point
                return round(avg_score, 2)

        # If no scores for this brand but there is a parent/ancestor with a score, use that
        if self.parent:
            root = self.root_brand
            if root and root.id != self.id:  # Make sure we don't get into an infinite loop
                root_score = root.score
                if root_score is not None:
                    return root_score

        # No scores found in the hierarchy
        return None

    @score.inplace.expression
    @classmethod
    def _score_expression(cls):
        """SQL expression for calculating brand score."""
        max_total_point = select(func.count(Criterion.id) * 5)\
            .label("max_total_point").scalar_subquery()
        total_score = select(func.sum(BrandCriterionScore.score))\
            .where(BrandCriterionScore.brand_id == cls.id).scalar_subquery()
        return case(
            (max_total_point == 0, None),
            else_=func.round((total_score * 100) / max_total_point, 2)
        )
