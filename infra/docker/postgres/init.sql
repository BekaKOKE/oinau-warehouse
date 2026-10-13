-- Расширения PostgreSQL, нужные проекту.
-- Выполняется один раз при первичной инициализации тома.

-- Поиск по подстроке и с опечатками (артикулы, названия товаров)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Нормализация диакритики при поиске
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Нужен для EXCLUDE-ограничений на диапазоны количества в ценовых ступенях
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Регистронезависимый тип для email пользователей
CREATE EXTENSION IF NOT EXISTS citext;

-- gen_random_uuid() для публичных идентификаторов
CREATE EXTENSION IF NOT EXISTS pgcrypto;
