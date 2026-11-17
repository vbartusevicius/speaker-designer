"""Strict Pydantic request schemas for FastAPI endpoints."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class FlexibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class OptimizeRequest(FlexibleModel):
    cabinet: dict[str, Any] = Field(default_factory=dict)
    sim: dict[str, Any] = Field(default_factory=dict)
    budget_eur_pair: float = Field(default=600.0, gt=0)
    ways: Literal["2", "3", "any"] = "3"
    crossover_mode: Literal["active", "passive"] = "active"
    box: Literal["auto", "sealed", "vented"] = "auto"
    port_location: Literal["front", "rear", "bottom"] = "front"
    min_tier: int = Field(default=1, ge=1, le=5)
    allow_dual_woofers: bool = True
    priorities: dict[str, float] = Field(default_factory=dict)
    in_stock_only: bool = False
    top_n: int = Field(default=8, ge=1, le=30)


class ReverseRequest(FlexibleModel):
    woofer: str
    woofer_count: int = Field(default=1, ge=1, le=4)
    mid: Optional[str] = None
    tweeter: str
    wall_t: float = Field(default=18.0, gt=0)
    alignment: Literal["auto", "sealed", "vented"] = "auto"
    crossover_mode: Literal["active", "passive"] = "active"
    port_location: Literal["front", "rear", "bottom"] = "front"
    layout_style: str = "vertical"
    fixed: dict[str, float] = Field(default_factory=dict)


class SubReverseRequest(FlexibleModel):
    woofer: str
    woofer_count: int = Field(default=1, ge=1, le=4)
    wall_t: float = Field(default=18.0, gt=0)
    alignment: Literal["auto", "sealed", "vented"] = "auto"
    fixed: dict[str, float] = Field(default_factory=dict)


class LayoutCheckRequest(FlexibleModel):
    design: dict[str, Any] = Field(default_factory=dict)
    port: Optional[dict[str, Any]] = None


class DriverImportRequest(BaseModel):
    id: str
    fetch_price: bool = True


class FetchPricesRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)
    force: bool = False


class MeasurementUploadRequest(BaseModel):
    text: str = ""
    source: str = "upload"
    filename: Optional[str] = None
