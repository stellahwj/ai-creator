"""
OpenAI-compatible image generation provider.
"""

import asyncio
import base64
import mimetypes
import os
import uuid

import requests

from app.providers import ImageProvider


class OpenAIProvider(ImageProvider):
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.size = os.getenv("OPENAI_IMAGE_SIZE", "1024x1024").strip()
        self.quality = os.getenv("OPENAI_IMAGE_QUALITY", "").strip()
        self.output_format = os.getenv("OPENAI_IMAGE_OUTPUT_FORMAT", "png").strip() or "png"

    async def generate(self, model_id, prompt, negative_prompt, img_path, user_dir, dl_base_name, user, target_ratio=""):
        if not self.api_key:
            raise Exception("OpenAI Error: OPENAI_API_KEY is not configured")

        final_prompt = self._build_prompt(prompt, negative_prompt, target_ratio)
        if img_path and os.path.exists(img_path):
            resp_json = await self._edit_image(model_id, final_prompt, img_path, user)
        else:
            resp_json = await self._generate_image(model_id, final_prompt, user)

        generated_images = await self._save_response_images(resp_json, user_dir, dl_base_name, user)
        return generated_images, ""

    def _build_prompt(self, prompt: str, negative_prompt: str, target_ratio: str) -> str:
        parts = [prompt]
        if target_ratio:
            parts.append(f"Please strictly generate or edit the image using a {target_ratio} aspect ratio.")
        if negative_prompt:
            parts.append(f"Negative constraints: {negative_prompt}")
        return "\n\n".join(part for part in parts if part)

    async def _generate_image(self, model_id: str, prompt: str, user: str) -> dict:
        payload = {
            "model": model_id,
            "prompt": prompt,
            "n": 1,
            "user": user,
        }
        self._add_optional_image_params(payload, model_id)
        if not self._is_gpt_image_model(model_id):
            payload["response_format"] = "b64_json"

        resp = await asyncio.to_thread(
            requests.post,
            self._url("/images/generations"),
            headers=self._json_headers(),
            json=payload,
            timeout=180,
        )
        return self._parse_response(resp)

    async def _edit_image(self, model_id: str, prompt: str, img_path: str, user: str) -> dict:
        data = {
            "model": model_id,
            "prompt": prompt,
            "n": "1",
            "user": user,
        }
        self._add_optional_image_params(data, model_id)

        mime_type = mimetypes.guess_type(img_path)[0] or "image/png"
        with open(img_path, "rb") as image_file:
            files = {"image": (os.path.basename(img_path), image_file, mime_type)}
            resp = await asyncio.to_thread(
                requests.post,
                self._url("/images/edits"),
                headers=self._auth_headers(),
                data=data,
                files=files,
                timeout=240,
            )
        return self._parse_response(resp)

    async def _save_response_images(self, resp_json: dict, user_dir: str, dl_base_name: str, user: str):
        generated_images = []
        for idx, item in enumerate(resp_json.get("data", [])):
            image_bytes = None
            ext = self.output_format.replace("jpeg", "jpg")

            if item.get("b64_json"):
                image_bytes = base64.b64decode(item["b64_json"])
            elif item.get("url"):
                img_data = await asyncio.to_thread(requests.get, item["url"], timeout=180)
                img_data.raise_for_status()
                image_bytes = img_data.content
                ext = self._extension_from_content_type(img_data.headers.get("Content-Type")) or ext

            if not image_bytes:
                continue

            filename = f"gen_{uuid.uuid4().hex[:8]}.{ext}"
            with open(os.path.join(user_dir, filename), "wb") as f:
                f.write(image_bytes)
            suffix = f"_{idx + 1}" if len(resp_json.get("data", [])) > 1 else ""
            generated_images.append({
                "url": f"/api/images/{user}/{filename}",
                "download_name": f"{dl_base_name}{suffix}.{ext}",
            })
        return generated_images

    def _add_optional_image_params(self, payload: dict, model_id: str):
        if self.size:
            payload["size"] = self.size
        if self.quality:
            payload["quality"] = self.quality
        if self._is_gpt_image_model(model_id) and self.output_format:
            payload["output_format"] = self.output_format.replace("jpg", "jpeg")

    def _parse_response(self, resp) -> dict:
        try:
            resp_json = resp.json()
        except ValueError as exc:
            raise Exception(f"OpenAI Error: invalid JSON response ({resp.text[:500]})") from exc

        if resp.status_code >= 400 or resp_json.get("error"):
            error = resp_json.get("error", {})
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise Exception(f"OpenAI Error: {message or resp.text[:500]}")
        return resp_json

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _json_headers(self) -> dict:
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        return headers

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _is_gpt_image_model(self, model_id: str) -> bool:
        return model_id.startswith("gpt-image")

    def _extension_from_content_type(self, content_type: str) -> str:
        if not content_type:
            return ""
        return {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }.get(content_type.split(";")[0].strip().lower(), "")
