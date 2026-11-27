from pydantic import BaseModel, Field


class NewPreview(BaseModel):
    port: int = Field(ge=1, le=65535, description="A port a server in the agent's workspace listens on")


class PreviewUrl(BaseModel):
    url: str = Field(description="Open within a minute: it signs the browser in to this one preview and then shows it")
