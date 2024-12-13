
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    city = Column(String, nullable=False)
    state = Column(String, nullable=False)

    sightings = relationship('Sightings', back_populates='user')

class Species(Base):
    __tablename__ = 'species'
    id = Column(Integer, primary_key=True)
    common_name = Column(String, nullable=False)
    genus = Column(String, nullable=False)
    species = Column(String, nullable=False)
    order = Column(String, nullable=False)
    wiki_url = Column(String, nullable=False)

    sightings = relationship('Sightings', back_populates='species')

class Sighting(Base):
    __tablename__ = 'sighting'
    id = Column(Integer, primary_key=True)
    species = Column(Integer, ForeignKey('Species.id'))
    user = Column(Integer, ForeignKey('User.id'))
    datetime = Column(DateTime, nullable=False)
    photo_location = Column(String)
    weather_conditions = Column(String)
    feed_type = Column(String)

    species = relationship('Species', back_populates='sightings')
    user = relationship('User', back_populates='sightings')

