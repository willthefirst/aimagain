from typing import Any


class APIResponse:
    @staticmethod
    def html_response(template_name: str, context: dict, request: Any) -> Any:
        """
        Helper for HTML responses using templates.
        Includes global template context for development features.
        """
        from src.core.templating import get_template_context, templates

        # Merge the provided context with global template context
        global_context = get_template_context()
        merged_context = {**global_context, **context}

        return templates.TemplateResponse(request, template_name, merged_context)
