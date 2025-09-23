import json
from pathlib import Path
from flask import current_app
from flask_script import Command
from app.models import SubCounty, Ward, db

class PopulateMombasaData(Command):
    """Load Mombasa location data from JSON file"""
    
    def run(self):
        data_path = Path(current_app.root_path) / "data" / "mombasa_locations.json"
        
        try:
            with open(data_path) as f:
                data = json.load(f)
                
            with db.session.begin_nested():  # Transaction
                for sc_data in data["subcounties"]:
                    subcounty = SubCounty.query.filter_by(name=sc_data["name"]).first()
                    if not subcounty:
                        subcounty = SubCounty(name=sc_data["name"], code=sc_data["code"])
                        db.session.add(subcounty)
                        db.session.flush()  # Get ID before adding wards
                    
                    for ward_name in sc_data["wards"]:
                        if not Ward.query.filter_by(name=ward_name, subcounty_id=subcounty.id).first():
                            db.session.add(Ward(name=ward_name, subcounty_id=subcounty.id))
            
            db.session.commit()
            print("✅ Mombasa data loaded successfully!")
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Failed to load data: {str(e)}")
            return False