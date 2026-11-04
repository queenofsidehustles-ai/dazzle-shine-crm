"""What makes a password acceptable when somebody chooses one.

One rule for every place a person picks a password: signing up, resetting it,
accepting an invite, changing it from their account. It used to be written out
in two places and had drifted: the reset and invite pages refused "qwertyui" and
signup did not.

The platform console's own passwords are held to a stricter rule on purpose
(console_admin.py, twelve characters) and are not chosen here.
"""

MIN_LENGTH = 8

# Refused whatever the length: the first things anybody would try.
TOO_EASY = ('password', '12345678', 'changeme', 'qwertyui')


def problem(pw, confirm):
    """Why this choice of password cannot be used, in words for the person
    choosing it, or None. `confirm` is what they typed the second time."""
    if len(pw) < MIN_LENGTH:
        return f'Please use at least {MIN_LENGTH} characters.'
    if pw != confirm:
        return 'The two passwords do not match.'
    if pw.lower() in TOO_EASY:
        return 'That password is too easy to guess.'
    return None
