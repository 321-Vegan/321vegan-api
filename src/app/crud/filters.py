from typing import Type, TypeVar, Tuple, Dict
from sqlalchemy.sql import operators, any_
from sqlalchemy import extract, func, or_
from sqlalchemy.orm import Query, RelationshipProperty, aliased

ORMModel = TypeVar("ORMModel")

RELATION_SPLITTER = '___'
OPERATOR_SPLITTER = '__'
OPERATOR_MAPPING = {
    'isnull': lambda c, v: (c == None) if v else (c != None),
    'exact': operators.eq,
    'ne': operators.ne,  # not equal or is not (for None)

    'gt': operators.gt,
    'ge': operators.ge,
    'lt': operators.lt,
    'le': operators.le,

    'in': operators.in_op,
    'iin': lambda c, v: func.lower(c).in_([item.lower() for item in v]) if v else True,
    'notin': operators.notin_op,
    'between': lambda c, v: c.between(v[0], v[1]),
    'any': lambda c, v:  v == any_(c),  # at least v is in c
    'overlap': lambda c, v: c.overlap(v),  # c and v share at least one item

    'like': operators.like_op,
    'ilike': operators.ilike_op,
    'startswith': operators.startswith_op,
    'istartswith': lambda c, v: c.ilike(v + '%'),
    'endswith': operators.endswith_op,
    'iendswith': lambda c, v: c.ilike('%' + v),
    'contains': lambda c, v: c.ilike('%{v}%'.format(v=v)),
    'lookalike': lambda c, v: or_(
        func.lower(func.trim(c)).like('%' + v.strip().lower() + '%'),
        func.levenshtein(func.lower(func.trim(c)), v.strip().lower()) <= 2,
    ),

    'year': lambda c, v: extract('year', c) == v,
    'year_ne': lambda c, v: extract('year', c) != v,
    'year_gt': lambda c, v: extract('year', c) > v,
    'year_ge': lambda c, v: extract('year', c) >= v,
    'year_lt': lambda c, v: extract('year', c) < v,
    'year_le': lambda c, v: extract('year', c) <= v,

    'month': lambda c, v: extract('month', c) == v,
    'month_ne': lambda c, v: extract('month', c) != v,
    'month_gt': lambda c, v: extract('month', c) > v,
    'month_ge': lambda c, v: extract('month', c) >= v,
    'month_lt': lambda c, v: extract('month', c) < v,
    'month_le': lambda c, v: extract('month', c) <= v,

    'day': lambda c, v: extract('day', c) == v,
    'day_ne': lambda c, v: extract('day', c) != v,
    'day_gt': lambda c, v: extract('day', c) > v,
    'day_ge': lambda c, v: extract('day', c) >= v,
    'day_lt': lambda c, v: extract('day', c) < v,
    'day_le': lambda c, v: extract('day', c) <= v,
}


def buildQueryFilters(model: Type[ORMModel], query: Query, filter_args: Dict) -> Query:
    """
    Builds query filters from query params.

    Parameters:
        model (ORMModel): The queried model class.
        query (Query): The query to hook the filter and filter_by
        filter_args: Variable number of keyword arguments for filtering
    Returns:
        Query: The given query with additional joins and filters (filter and filter_by).
    """
    try:
        filters_by = {}
        relations = [c.key for c in model.__mapper__.attrs
                     if isinstance(c, RelationshipProperty)]
        for field, value in filter_args.items():
            if RELATION_SPLITTER in field:
                # Filters by relationship attributes
                relation_field, rest = field.split(RELATION_SPLITTER, 1)
                if relation_field in relations:
                    relationship = getattr(model, relation_field)
                    # aliased for self relationship case
                    r_class = aliased(relationship.property.mapper.class_)
                    # handle recursive cross-relationship
                    if RELATION_SPLITTER in rest:
                        query = buildQueryFilters(r_class, query.join(
                            r_class, relationship), {rest: value})
                    if OPERATOR_SPLITTER in rest:
                        r_field, ope = rest.rsplit(OPERATOR_SPLITTER, 1)
                    else:
                        r_field = rest
                        ope = 'exact'
                    r_attr = getattr(r_class, r_field)
                    if r_attr is None or ope not in OPERATOR_MAPPING:
                        continue
                    operator = OPERATOR_MAPPING[ope]
                    clause = operator(r_attr, value)
                    # Join aliased relationship and filter on it
                    query = query.join(r_class, relationship).filter(clause)
            elif OPERATOR_SPLITTER in field:
                # Filter with custom operator
                field_name, ope = field.split(OPERATOR_SPLITTER, 1)
                if hasattr(model, field_name) and ope in OPERATOR_MAPPING:
                    operator = OPERATOR_MAPPING[ope]
                    m_attr = getattr(model, field_name)
                    clause = operator(m_attr, value)
                    # Filter on queried model
                    query = query.filter(clause)
            elif hasattr(model, field):
                # Simple filter
                query = query.filter(getattr(model, field) == value)
        return query
    except Exception as e:
        print(f"error in buildQueryFilters : {e}")
        return query
