"""Helper to deal with querystring parameters according to jsonapi specification"""

import simplejson as json

from flask import current_app

from flask_combo_jsonapi.exceptions import BadRequest, InvalidFilters, InvalidSort, InvalidField, InvalidInclude
from flask_combo_jsonapi.schema import get_model_field, get_relationships, get_schema_from_type
from flask_combo_jsonapi.utils import SPLIT_REL


class QueryStringManager(object):
    """Querystring parser according to jsonapi reference"""

    MANAGED_KEYS = (
        'filter',
        'page',
        'fields',
        'sort',
        'include',
        'q'
    )

    def __init__(self, querystring, schema):
        """Initialization instance

        :param dict querystring: query string dict from request.args
        """
        if not isinstance(querystring, dict):
            raise ValueError('QueryStringManager require a dict-like object querystring parameter')

        self.qs = querystring
        self.schema = schema

    def _get_key_values(self, name):
        """Return a dict containing key / values items for a given key, used for items like filters, page, etc.

        :param str name: name of the querystring parameter
        :return dict: a dict of key / values items
        """
        results = {}

        for key, value in self.qs.items():
            try:
                if not key.startswith(name):
                    continue

                key_start = key.index('[') + 1
                key_end = key.index(']')
                item_key = key[key_start:key_end]

                if ',' in value:
                    item_value = value.split(',')
                else:
                    item_value = value
                results.update({item_key: item_value})
            except Exception:
                raise BadRequest("Parse error", source={'parameter': key})

        return results

    def _simple_filters(self, dict_):
        return [{"name": key, "op": "eq", "val": value}
                for (key, value) in dict_.items()]

    @property
    def querystring(self):
        """Return original querystring but containing only managed keys

        :return dict: dict of managed querystring parameter
        """
        return {key: value for (key, value) in self.qs.items()
                if key.startswith(self.MANAGED_KEYS) or self._get_key_values('filter[')}

    @property
    def filters(self):
        """Return filters from query string.

        :return list: filter information
        """
        results = []
        filters = self.qs.get('filter')
        if filters is not None:
            try:
                results.extend(json.loads(filters))
            except (ValueError, TypeError):
                raise InvalidFilters("Parse error")
        if self._get_key_values('filter['):
            results.extend(self._simple_filters(self._get_key_values('filter[')))
        return results

    @property
    def pagination(self):
        """Return parameters page[size] and page[number) as a dict.
        If missing parmeter `size` then default parameter PAGE_SIZE is used.

        :return dict: a dict of pagination information

        Example with number strategy::

            >>> query_string = {'page[number]': '25', 'page[size]': '10'}
            >>> parsed_query.pagination
            {'number': 25, 'size': 10}
        """
        # check values type
        result = self._get_key_values('page')
        for key, value in result.items():
            if key not in ('number', 'size'):
                raise BadRequest("{} is not a valid parameter of pagination".format(key), source={'parameter': 'page'})
            try:
                result[key] = int(value)
            except ValueError:
                raise BadRequest("Parse error", source={'parameter': 'page[{}]'.format(key)})

        result.setdefault('size', current_app.config.get('PAGE_SIZE', 30))

        if current_app.config.get('ALLOW_DISABLE_PAGINATION', True) is False and result.get('size') == 0:
            raise BadRequest("You are not allowed to disable pagination", source={'parameter': 'page[size]'})

        if current_app.config.get('MAX_PAGE_SIZE') is not None and 'size' in result:
            if int(result['size']) > current_app.config['MAX_PAGE_SIZE']:
                raise BadRequest("Maximum page size is {}".format(current_app.config['MAX_PAGE_SIZE']),
                                 source={'parameter': 'page[size]'})

        return result

    @property
    def fields(self):
        """Return fields wanted by client.

        :return dict: a dict of sparse fieldsets information

        Return value will be a dict containing all fields by resource, for example::

            {
                "user": ['name', 'email'],
            }

        """
        result = self._get_key_values('fields')
        for key, value in result.items():
            if not isinstance(value, list):
                result[key] = [value]

        for key, value in result.items():
            schema = get_schema_from_type(key)
            for obj in value:
                if obj not in schema._declared_fields:
                    raise InvalidField("{} has no attribute {}".format(schema.__name__, obj))

        return result

    @property
    def sorting(self):
        """Return fields to sort by including sort name for SQLAlchemy and row
        sort parameter for other ORMs

        :return list: a list of sorting information

        Example of return value::

            [
                {'field': 'created_at', 'order': 'desc'},
            ]

        """
        if self.qs.get('sort'):
            sorting_results = []
            for sort_field in self.qs['sort'].split(','):
                field = sort_field.replace('-', '')
                if SPLIT_REL not in field:
                    if field not in self.schema._declared_fields:
                        raise InvalidSort("{} has no attribute {}".format(self.schema.__name__, field))
                    if field in get_relationships(self.schema):
                        raise InvalidSort("You can't sort on {} because it is a relationship field".format(field))
                    field = get_model_field(self.schema, field)
                order = 'desc' if sort_field.startswith('-') else 'asc'
                sorting_results.append({'field': field, 'order': order})
            return sorting_results

        return []

    @property
    def include(self):
        """Return fields to include

        :return list: a list of include information
        """
        include_param = self.qs.get('include', [])

        if current_app.config.get('MAX_INCLUDE_DEPTH') is not None:
            for include_path in include_param:
                if len(include_path.split(SPLIT_REL)) > current_app.config['MAX_INCLUDE_DEPTH']:
                    raise InvalidInclude("You can't use include through more than {} relationships"
                                         .format(current_app.config['MAX_INCLUDE_DEPTH']))

        return include_param.split(',') if include_param else []
