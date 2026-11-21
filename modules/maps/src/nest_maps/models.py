"""The maps' tables: a map (its centre and zoom) and its markers."""

from __future__ import annotations

from nest_db import model_base, text_table
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("maps")


class Map(Base):
    __tablename__ = "maps_map"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    zoom: Mapped[int] = mapped_column(Integer, default=13)
    # Its id in WP Google Maps, so [wpgmza id="1"] in a moved page still shows it.
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class Marker(Base):
    __tablename__ = "maps_marker"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("maps_map.id", ondelete="CASCADE"), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(500), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)


# Their words in each language of the site, one row per language, the default one's
# mirroring the records' own (written with them). A marker without words has none.
MapText = text_table(Base, Map, title=String(200), description=Text)
MarkerText = text_table(Base, Marker, title=String(200), description=Text)
