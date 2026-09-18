BEGIN;

-- Catálogos independientes.
CREATE TABLE formats (
    format_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name varchar(80) NOT NULL,
    description text,
    CONSTRAINT uq_formats_name UNIQUE (name),
    CONSTRAINT ck_formats_name_not_blank CHECK (btrim(name) <> '')
);

CREATE TABLE categories (
    category_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name varchar(120) NOT NULL,
    description text,
    CONSTRAINT uq_categories_name UNIQUE (name),
    CONSTRAINT ck_categories_name_not_blank CHECK (btrim(name) <> '')
);

CREATE TABLE genres (
    genre_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name varchar(120) NOT NULL,
    description text,
    CONSTRAINT uq_genres_name UNIQUE (name),
    CONSTRAINT ck_genres_name_not_blank CHECK (btrim(name) <> '')
);

CREATE TABLE authors (
    author_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    first_name varchar(120) NOT NULL,
    last_name varchar(120),
    biography text,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_authors_first_name_not_blank CHECK (btrim(first_name) <> ''),
    CONSTRAINT ck_authors_last_name_not_blank
        CHECK (last_name IS NULL OR btrim(last_name) <> '')
);

CREATE TABLE users (
    user_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email varchar(254) NOT NULL,
    password_hash text NOT NULL,
    display_name varchar(150) NOT NULL,
    is_admin boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Servicio login (services/login): nombre de la persona en columnas atómicas (1FN).
    -- NULL en cuentas creadas por el monolito, que solo conocen display_name.
    nombre varchar(120),
    apellido_paterno varchar(120),
    apellido_materno varchar(120),
    -- Servicio login: NULL = correo sin confirmar. El default marca como verificadas las cuentas
    -- que crea el monolito (las crea un administrador); el servicio login inserta NULL en los registros públicos.
    email_verified_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT ck_users_email_not_blank CHECK (btrim(email) <> ''),
    CONSTRAINT ck_users_password_hash_not_blank CHECK (btrim(password_hash) <> ''),
    CONSTRAINT ck_users_display_name_not_blank CHECK (btrim(display_name) <> ''),
    CONSTRAINT ck_users_person_name CHECK (
        num_nulls(nombre, apellido_paterno, apellido_materno) IN (0, 3)
        AND coalesce(btrim(nombre), 'x') <> ''
        AND coalesce(btrim(apellido_paterno), 'x') <> ''
        AND coalesce(btrim(apellido_materno), 'x') <> ''
    )
);

-- Un mismo correo no puede repetirse cambiando mayúsculas/minúsculas (login y registro comparan en minúsculas).
CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email));

-- Un índice único parcial sobre una constante permite como máximo un administrador.
CREATE UNIQUE INDEX uq_users_single_administrator
    ON users ((is_admin))
    WHERE is_admin;

CREATE TABLE books (
    book_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    isbn varchar(17) NOT NULL,
    title varchar(300) NOT NULL,
    publication_year smallint NOT NULL,
    price numeric(12, 2) NOT NULL,
    stock integer NOT NULL DEFAULT 0,
    format_id bigint NOT NULL,
    category_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_books_isbn UNIQUE (isbn),
    CONSTRAINT fk_books_format FOREIGN KEY (format_id)
        REFERENCES formats (format_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_books_category FOREIGN KEY (category_id)
        REFERENCES categories (category_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_books_isbn CHECK (
        isbn ~ '^(?:[0-9]{9}[0-9X]|[0-9]{13}|[0-9]{1,5}-[0-9]+-[0-9]+-[0-9X])$'
    ),
    CONSTRAINT ck_books_title_not_blank CHECK (btrim(title) <> ''),
    CONSTRAINT ck_books_publication_year CHECK (publication_year BETWEEN 1000 AND 9999),
    CONSTRAINT ck_books_price_nonnegative CHECK (price >= 0),
    CONSTRAINT ck_books_stock_nonnegative CHECK (stock >= 0)
);

-- Resuelve la dependencia multivaluada libro ->> autor.
CREATE TABLE book_authors (
    book_id bigint NOT NULL,
    author_id bigint NOT NULL,
    author_order smallint NOT NULL DEFAULT 1,
    PRIMARY KEY (book_id, author_id),
    CONSTRAINT uq_book_authors_order UNIQUE (book_id, author_order),
    CONSTRAINT fk_book_authors_book FOREIGN KEY (book_id)
        REFERENCES books (book_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_book_authors_author FOREIGN KEY (author_id)
        REFERENCES authors (author_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_book_authors_order_positive CHECK (author_order > 0)
);

-- Resuelve la dependencia multivaluada libro ->> género.
CREATE TABLE book_genres (
    book_id bigint NOT NULL,
    genre_id bigint NOT NULL,
    PRIMARY KEY (book_id, genre_id),
    CONSTRAINT fk_book_genres_book FOREIGN KEY (book_id)
        REFERENCES books (book_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_book_genres_genre FOREIGN KEY (genre_id)
        REFERENCES genres (genre_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE concepts (
    concept_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name varchar(200) NOT NULL,
    CONSTRAINT uq_concepts_name UNIQUE (name),
    CONSTRAINT ck_concepts_name_not_blank CHECK (btrim(name) <> '')
);

-- La definición depende del par (libro, concepto), no solo del concepto.
CREATE TABLE book_concepts (
    book_id bigint NOT NULL,
    concept_id bigint NOT NULL,
    definition text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (book_id, concept_id),
    CONSTRAINT fk_book_concepts_book FOREIGN KEY (book_id)
        REFERENCES books (book_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_book_concepts_concept FOREIGN KEY (concept_id)
        REFERENCES concepts (concept_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_book_concepts_definition_not_blank CHECK (btrim(definition) <> '')
);

-- Se almacena la referencia al recurso; el binario puede vivir en disco u object storage.
CREATE TABLE book_images (
    image_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id bigint NOT NULL,
    image_url text NOT NULL,
    alt_text varchar(300),
    display_order smallint NOT NULL DEFAULT 1,
    is_cover boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_book_images_url UNIQUE (book_id, image_url),
    CONSTRAINT uq_book_images_order UNIQUE (book_id, display_order),
    CONSTRAINT fk_book_images_book FOREIGN KEY (book_id)
        REFERENCES books (book_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT ck_book_images_url_not_blank CHECK (btrim(image_url) <> ''),
    CONSTRAINT ck_book_images_alt_text_not_blank
        CHECK (alt_text IS NULL OR btrim(alt_text) <> ''),
    CONSTRAINT ck_book_images_order_positive CHECK (display_order > 0)
);

-- Un libro puede tener muchas imágenes, pero solo una portada.
CREATE UNIQUE INDEX uq_book_images_single_cover
    ON book_images (book_id)
    WHERE is_cover;

-- Sesiones del servicio login (1 usuario : N sesiones). Duran 30 minutos (expires_at) y son
-- revocables (logout). last_login NO se guarda en users: se deriva de MAX(login_sessions.created_at).
CREATE TABLE login_sessions (
    session_id uuid PRIMARY KEY,
    user_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    ip_address inet,
    user_agent varchar(400),
    CONSTRAINT fk_login_sessions_user FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT ck_login_sessions_expiry CHECK (expires_at > created_at)
);

CREATE INDEX ix_login_sessions_user_id ON login_sessions (user_id);
CREATE INDEX ix_login_sessions_active_expiry ON login_sessions (expires_at) WHERE revoked_at IS NULL;

-- Tokens de confirmación de correo (servicio login). Solo se guarda el SHA-256 del token que viaja en el enlace.
CREATE TABLE email_verifications (
    verification_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL,
    token_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    CONSTRAINT uq_email_verifications_token UNIQUE (token_hash),
    CONSTRAINT fk_email_verifications_user FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT ck_email_verifications_hash CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_email_verifications_expiry CHECK (expires_at > created_at)
);

CREATE INDEX ix_email_verifications_user_id ON email_verifications (user_id);

-- Índices para búsquedas y joins desde el lado no cubierto por las PK compuestas.
CREATE INDEX ix_books_format_id ON books (format_id);
CREATE INDEX ix_books_category_id ON books (category_id);
CREATE INDEX ix_book_authors_author_id ON book_authors (author_id);
CREATE INDEX ix_book_genres_genre_id ON book_genres (genre_id);
CREATE INDEX ix_book_concepts_concept_id ON book_concepts (concept_id);
CREATE INDEX ix_book_images_book_id ON book_images (book_id);

COMMIT;
