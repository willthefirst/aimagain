from typing import Any, Optional

from fastapi.responses import JSONResponse


class APIResponse:
    @staticmethod
    def success(
        data: Any, message: str = "Success", status_code: int = 200
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"status": "success", "message": message, "data": data},
        )

    @staticmethod
    def error(
        message: str, status_code: int = 400, code: Optional[str] = None
    ) -> JSONResponse:
        content = {"status": "error", "message": message}
        if code:
            content["code"] = code
        return JSONResponse(status_code=status_code, content=content)

    @staticmethod
    def html_response(template_name: str, context: dict, request: Any) -> Any:
        """
        Helper for HTML responses using templates.
        Includes global template context for development features.
        """
        from src.core.templating import get_template_context, templates

        # Merge the provided context with global template context
        global_context = get_template_context()
        merged_context = {"request": request, **global_context, **context}

        return templates.TemplateResponse(template_name, merged_context)
