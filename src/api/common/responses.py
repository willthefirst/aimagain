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
        Placeholder until templating engine is integrated.
        """
        from src.core.templating import templates

        return templates.TemplateResponse(
            template_name, {"request": request, **context}
        )
