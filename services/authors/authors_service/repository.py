"""Acceso a datos de Authors: SOLO funciones SQL (fn_authors_*, migración 008)."""

AUTHOR_ERRORS = {
    "AU001": (404, "not_found", None),
    "AU002": (404, "book_not_found", None),
    "AU003": (409, "already_linked", None),
    "AU004": (404, "link_not_found", None),
}


class AuthorsRepository:
    def __init__(self, pg):
        self.pg = pg

    def ping(self):
        self.pg.ping()

    def list(self, limit, offset):
        return self.pg.query("SELECT * FROM fn_authors_list(%s, %s)", (limit, offset))

    def get(self, author_id):
        return self.pg.one("SELECT * FROM fn_authors_get(%s)", (author_id,))

    def books(self, author_id):
        return self.pg.query("SELECT * FROM fn_authors_books(%s)", (author_id,))

    def create(self, first_name, last_name, biography):
        return self.pg.one("SELECT fn_authors_create(%s, %s, %s) AS id", (first_name, last_name, biography))["id"]

    def update(self, author_id, first_name, last_name, biography, replace):
        self.pg.query("SELECT fn_authors_update(%s, %s, %s, %s, %s)", (author_id, first_name, last_name, biography, replace))

    def delete(self, author_id):
        self.pg.query("SELECT fn_authors_delete(%s)", (author_id,))

    def link_book(self, author_id, isbn, author_order):
        self.pg.query("SELECT fn_authors_link_book(%s, %s, %s::smallint)", (author_id, isbn, author_order))

    def unlink_book(self, author_id, isbn):
        self.pg.query("SELECT fn_authors_unlink_book(%s, %s)", (author_id, isbn))
