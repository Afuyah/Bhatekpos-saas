from app import db
from app.models import SubCounty, Ward


def populate_mombasa_data():
    with app.app_context():
        # Mombasa SubCounties
        subcounties = [
            ('Changamwe', 'CHG'),
            ('Jomvu', 'JMV'),
            ('Kisauni', 'KIS'),
            ('Likoni', 'LKN'),
            ('Mvita', 'MVT'),
            ('Nyali', 'NYL')
        ]

        # Wards data (subcounty_name: [wards])
        wards_data = {
            'Changamwe': ['Port Reitz', 'Kipevu', 'Airport', 'Changamwe', 'Chaani'],
            'Jomvu': ['Jomvu Kuu', 'Miritini', 'Mikindani'],
            'Kisauni': ['Mjambere', 'Junda', 'Bamburi', 'Mwakirunge', 'Mtopanga', 'Mikindani'],
            'Likoni': ['Likoni', 'Timbwani', 'Shika Adabu', 'Bofu', 'Mtongwe', 'Tsimba Golini'],
            'Mvita': ['Mji wa Kale', 'Tudor', 'Tononoka', 'Shimanzi', 'Majengo'],
            'Nyali': ['Frere Town', 'Ziwa la Ngombe', 'Mkomani', 'Kongowea', 'Kadzandani']
        }

        for name, code in subcounties:
            subcounty = SubCounty.query.filter_by(name=name).first()
            if not subcounty:
                subcounty = SubCounty(name=name, code=code)
                db.session.add(subcounty)
                db.session.commit()
            
            for ward_name in wards_data[name]:
                ward = Ward.query.filter_by(name=ward_name, subcounty_id=subcounty.id).first()
                if not ward:
                    ward = Ward(name=ward_name, subcounty_id=subcounty.id)
                    db.session.add(ward)
        
        db.session.commit()
        print("Mombasa data populated successfully!")