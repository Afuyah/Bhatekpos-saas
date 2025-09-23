from marshmallow import Schema, fields, validate

class RegistrationSchema(Schema):
    username = fields.Str(required=True, validate=validate.Length(min=3))
    email = fields.Email(required=False, allow_none=True)
    password = fields.Str(required=True, validate=validate.Length(min=6))
    first_name = fields.Str(required=False)
    last_name = fields.Str(required=False)
    phone = fields.Str(required=False)
