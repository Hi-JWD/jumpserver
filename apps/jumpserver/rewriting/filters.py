from rest_framework.filters import SearchFilter as DRFSearchFilter


class SearchFilter(DRFSearchFilter):
    def get_search_fields(self, view, request):
        fields = getattr(view, 'search_fields', None)
        search_fields_func = getattr(view, 'get_search_fields', None)
        if callable(search_fields_func):
            fields = search_fields_func(request)
        return fields
