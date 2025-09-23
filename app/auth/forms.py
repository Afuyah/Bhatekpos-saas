from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, TextAreaField, BooleanField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional
from wtforms.validators import ValidationError

import re  
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=150)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    first_name = StringField('First Name', validators=[Optional(), Length(max=50)])
    last_name = StringField('Last Name', validators=[Optional(), Length(max=50)])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])

    def validate_username(self, field):
        if field.data.isdigit():
            raise ValidationError("Username cannot be only numbers.")
        if not re.match(r"^[a-zA-Z0-9_]+$", field.data):
            raise ValidationError("Username can only contain letters, numbers, and underscores.")

    def validate_password(self, field):
        if not re.match(r"^(?=.*[A-Z])(?=.*\d).{8,}$", field.data):
            raise ValidationError(
                "Password must be at least 8 characters with an uppercase letter and a number."
            )

    def validate_phone(self, field):
        if field.data and not re.match(r"^\+?1?\d{9,15}$", field.data):
            raise ValidationError("Invalid phone number format.")



class AddressForm(FlaskForm):
    county = SelectField(
        'County',
        coerce=lambda x: int(x) if x else None,  # Handle empty string
        validators=[DataRequired()],
        choices=[('', 'Select County')]  # Add empty default option
    )
    subcounty = SelectField(
        'Subcounty',
        coerce=lambda x: int(x) if x else None,
        validators=[DataRequired()],
        choices=[('', 'Select Subcounty')]
    )
    ward = SelectField(
        'Ward',
        coerce=lambda x: int(x) if x else None,
        validators=[DataRequired()],
        choices=[('', 'Select Ward')]
    )
    estate = StringField('Estate/Neighborhood', validators=[Optional()])
    landmark = StringField('Landmark', validators=[Optional()])
    building = StringField('Building', validators=[Optional()])
    apartment = StringField('Apartment', validators=[Optional()])
    house_number = StringField('House Number', validators=[Optional()])
    notes = TextAreaField('Delivery Notes', validators=[Optional()])
    is_primary = BooleanField('Set as primary address', default=True)
    submit = SubmitField('Save Address')