from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.types import Scope

# The engine is tens of megabytes. A hosted image keeps a gzipped copy beside each of these.
COMPRESSED_TYPES = {".wasm": "application/wasm", ".pck": "application/octet-stream"}


class StudioFiles(StaticFiles):
    """The built page. Revalidated every load, so a deploy cannot mix old and new engine files."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await self._compressed(path, scope) or await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        if path.endswith(".wasm"):
            response.headers["Content-Type"] = COMPRESSED_TYPES[".wasm"]
        return response

    async def _compressed(self, path: str, scope: Scope) -> Response | None:
        content_type = next((t for s, t in COMPRESSED_TYPES.items() if path.endswith(s)), None)
        if content_type is None or "gzip" not in Headers(scope=scope).get("accept-encoding", ""):
            return None
        _, stat = self.lookup_path(f"{path}.gz")
        if stat is None:
            return None
        response = await super().get_response(f"{path}.gz", scope)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Type"] = content_type
        response.headers["Vary"] = "Accept-Encoding"
        return response
