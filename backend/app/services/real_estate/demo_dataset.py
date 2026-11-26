import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import openpyxl

from app.core.config import settings

logger = logging.getLogger("demo_dataset")

# Location synonyms mapping for Indian real estate markets
LOCATION_SYNONYMS: Dict[str, List[str]] = {
    "gurugram": ["gurgaon", "gurugram", "gurgram", "sohna", "sohna road", "golf course road", "sector 42", "sector 54"],
    "bengaluru": ["bangalore", "bengaluru", "whitefield", "electronic city", "sarjapur", "sarjapur road", "bellandur", "hebbal"],
    "mumbai": ["mumbai", "bombay", "thane", "navi mumbai", "worli", "bandra", "andheri", "powai", "lower parel"],
    "chennai": ["chennai", "madras", "omr", "ecr", "porur", "sholinganallur", "velachery", "anna nagar"],
    "noida": ["noida", "greater noida", "yamuna expressway", "sector 150", "sector 128"],
    "pune": ["pune", "poona", "hinjewadi", "kharadi", "wakad", "baner", "koregaon park"],
    "delhi": ["delhi", "new delhi", "south delhi", "dwarka", "rohini"],
    "hyderabad": ["hyderabad", "cyberabad", "gachibowli", "hitec city", "jubilee hills", "kondapur"],
    "kolkata": ["kolkata", "calcutta", "new town", "rajarhat", "alipore"],
    "kochi": ["kochi", "cochin", "marine drive", "kakkanad"],
}


class DemoDatasetService:
    """
    In-memory service loading and validating BrainMagic_RealEstate.xlsx.
    Provides fast, grounded search and contextual query capabilities for:
    - Projects & Project Knowledge (amenities, developer, possession, official links)
    - Configurations (BHK layouts, area ranges, configuration price ranges)
    - Real Estate FAQs (terminology, RERA, customer questions)
    - Demo Apartments (estimated demo prices, units, blocks, floor variants)
    """

    _instance: Optional["DemoDatasetService"] = None

    def __init__(self, excel_path: Optional[str] = None):
        self.excel_path = excel_path or getattr(settings, "DEMO_DATASET_PATH", "BrainMagic_RealEstate.xlsx")
        self.is_loaded = False
        
        # In-memory indexes
        self.all_projects: Dict[str, Dict[str, Any]] = {}
        self.projects: Dict[str, Dict[str, Any]] = {}  # Saleable projects only
        self.all_configurations: Dict[str, Dict[str, Any]] = {}
        self.configurations: Dict[str, Dict[str, Any]] = {}  # Saleable configurations only
        self.project_configurations: Dict[str, List[Dict[str, Any]]] = {}
        self.faqs: List[Dict[str, Any]] = []
        self.project_faqs: Dict[str, List[Dict[str, Any]]] = {}
        self.demo_apartments: Dict[str, Dict[str, Any]] = {}
        self.project_demo_apartments: Dict[str, List[Dict[str, Any]]] = {}
        
        # Alias and name lookups
        self.project_name_index: Dict[str, str] = {}  # normalized name -> project_id
        
        # Load immediately
        self.load_dataset()

    @classmethod
    def get_instance(cls) -> "DemoDatasetService":
        if cls._instance is None:
            cls._instance = DemoDatasetService()
        return cls._instance

    def load_dataset(self) -> None:
        """Reads and validates all four worksheets."""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        candidates = [
            os.path.join(base_dir, "BrainMagic_RealEstate.xlsx"),
            os.path.join(backend_dir, "BrainMagic_RealEstate.xlsx"),
            self.excel_path,
            os.path.join(os.getcwd(), self.excel_path),
            os.path.join(os.getcwd(), "backend", self.excel_path),
        ]
        found_path = None
        for p in candidates:
            if p and os.path.exists(p):
                found_path = p
                break

        if not found_path:
            logger.error(f"[DemoDataset] File not found at any candidate paths: {candidates}")
            return

        self.excel_path = found_path
        logger.info(f"[DemoDataset] Loading demo dataset from {self.excel_path}...")
        try:
            wb = openpyxl.load_workbook(self.excel_path, data_only=True)
        except Exception as e:
            logger.error(f"[DemoDataset] Failed to load workbook: {e}")
            return

        # 1. Sheet: Property_Knowledge
        self.all_projects.clear()
        self.projects.clear()
        self.project_name_index.clear()
        if "Property_Knowledge" in wb.sheetnames:
            sheet = wb["Property_Knowledge"]
            headers = [cell.value for cell in next(sheet.iter_rows(max_row=1))]
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if not any(row):
                    continue
                record = dict(zip(headers, row))
                proj_id = str(record.get("Project_ID") or "").strip()
                if not proj_id:
                    continue

                self.all_projects[proj_id] = record

                # Filter duplicate aliases or portfolio summaries from saleable properties
                record_type = str(record.get("Record_Type") or "").strip().lower()
                if "duplicate" in record_type or "portfolio_summary" in record_type:
                    continue

                self.projects[proj_id] = record
                proj_name = str(record.get("Project_Name") or "").strip()
                if proj_name:
                    self.project_name_index[proj_name.lower()] = proj_id

        # 2. Sheet: Property_Configurations
        self.all_configurations.clear()
        self.configurations.clear()
        self.project_configurations.clear()
        if "Property_Configurations" in wb.sheetnames:
            sheet = wb["Property_Configurations"]
            headers = [cell.value for cell in next(sheet.iter_rows(max_row=1))]
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if not any(row):
                    continue
                record = dict(zip(headers, row))
                cfg_id = str(record.get("Configuration_ID") or "").strip()
                proj_id = str(record.get("Project_ID") or "").strip()
                if not cfg_id:
                    continue

                self.all_configurations[cfg_id] = record

                # Filter duplicate or portfolio summaries
                record_type = str(record.get("Record_Type") or "").strip().lower()
                if "duplicate" in record_type or "portfolio_summary" in record_type:
                    continue

                self.configurations[cfg_id] = record
                if proj_id:
                    self.project_configurations.setdefault(proj_id, []).append(record)

        # 3. Sheet: RealEstate_FAQs
        self.faqs.clear()
        self.project_faqs.clear()
        if "RealEstate_FAQs" in wb.sheetnames:
            sheet = wb["RealEstate_FAQs"]
            headers = [cell.value for cell in next(sheet.iter_rows(max_row=1))]
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if not any(row):
                    continue
                record = dict(zip(headers, row))
                faq_id = str(record.get("FAQ_ID") or "").strip()
                if not faq_id:
                    continue
                self.faqs.append(record)
                proj_id = str(record.get("Project_ID") or "").strip()
                if proj_id:
                    self.project_faqs.setdefault(proj_id, []).append(record)

        # 4. Sheet: Demo_Apartments
        self.demo_apartments.clear()
        self.project_demo_apartments.clear()
        if "Demo_Apartments" in wb.sheetnames:
            sheet = wb["Demo_Apartments"]
            headers = [cell.value for cell in next(sheet.iter_rows(max_row=1))]
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if not any(row):
                    continue
                record = dict(zip(headers, row))
                apt_id = str(record.get("Demo_Apartment_ID") or "").strip()
                proj_id = str(record.get("Project_ID") or "").strip()
                if not apt_id:
                    continue

                self.demo_apartments[apt_id] = record
                if proj_id:
                    self.project_demo_apartments.setdefault(proj_id, []).append(record)

        self.is_loaded = True
        logger.info(
            f"[DemoDataset] Successfully loaded: {len(self.projects)} projects, "
            f"{len(self.configurations)} configurations, {len(self.faqs)} FAQs, "
            f"{len(self.demo_apartments)} demo apartments."
        )

    def _matches_location(self, query: str, city: str, locality: str, address: str) -> bool:
        """Helper to match city or locality with synonym expansion."""
        q = query.strip().lower()
        target = f"{city} {locality} {address}".lower()
        if q in target:
            return True
        # Check synonyms
        for canonical, syns in LOCATION_SYNONYMS.items():
            if q == canonical or q in syns:
                if any(s in target for s in syns) or canonical in target:
                    return True
        return False

    def search_properties(
        self,
        city: Optional[str] = None,
        locality: Optional[str] = None,
        project_name: Optional[str] = None,
        developer: Optional[str] = None,
        property_type: Optional[str] = None,
        bhk: Optional[int] = None,
        min_budget: Optional[float] = None,
        max_budget: Optional[float] = None,
        amenities: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Searches projects and matching demo apartments across all criteria.
        """
        results: List[Dict[str, Any]] = []

        for proj_id, proj in self.projects.items():
            # City & Location filtering
            proj_city = str(proj.get("City") or "")
            proj_loc = str(proj.get("Locality") or "")
            proj_addr = str(proj.get("Full_Address") or "")

            if city and not self._matches_location(city, proj_city, proj_loc, proj_addr):
                continue
            if locality and not self._matches_location(locality, proj_city, proj_loc, proj_addr):
                continue

            # Developer filtering
            proj_dev = str(proj.get("Developer_Name") or "").lower()
            if developer and developer.lower() not in proj_dev:
                continue

            # Project name filtering
            pname = str(proj.get("Project_Name") or "").lower()
            if project_name and project_name.lower() not in pname:
                continue

            # Property type
            ptype = str(proj.get("Project_Type") or proj.get("Property_Category") or "").lower()
            if property_type and property_type.lower() not in ptype:
                continue

            # Check matching demo apartments & configurations for BHK / budget
            apts = self.project_demo_apartments.get(proj_id, [])
            cfgs = self.project_configurations.get(proj_id, [])
            
            matching_apts = []
            matching_cfgs = []

            for cfg in cfgs:
                cfg_bhk = cfg.get("BHK")
                try:
                    cfg_bhk_int = int(cfg_bhk) if cfg_bhk is not None else None
                except (ValueError, TypeError):
                    cfg_bhk_int = None
                
                if bhk is not None and cfg_bhk_int != bhk:
                    continue
                matching_cfgs.append(cfg)

            for apt in apts:
                apt_bhk = apt.get("BHK_DEMO")
                try:
                    apt_bhk_int = int(apt_bhk) if apt_bhk is not None else None
                except (ValueError, TypeError):
                    apt_bhk_int = None

                if bhk is not None and apt_bhk_int != bhk:
                    continue

                # Budget filtering
                apt_pmin = apt.get("Price_Min_INR_DEMO")
                apt_pmax = apt.get("Price_Max_INR_DEMO")
                try:
                    pmin = float(apt_pmin) if apt_pmin is not None else 0.0
                    pmax = float(apt_pmax) if apt_pmax is not None else pmin
                except (ValueError, TypeError):
                    pmin, pmax = 0.0, 0.0

                if max_budget is not None and pmin > max_budget:
                    continue
                if min_budget is not None and pmax < min_budget and pmax > 0:
                    continue

                matching_apts.append(apt)

            if bhk is not None and not matching_apts and not matching_cfgs:
                continue
            if (min_budget is not None or max_budget is not None) and not matching_apts:
                # Check project overall price
                proj_pmin = proj.get("Demo_Project_Price_Min_INR")
                proj_pmax = proj.get("Demo_Project_Price_Max_INR")
                try:
                    ppmin = float(proj_pmin) if proj_pmin else 0.0
                    ppmax = float(proj_pmax) if proj_pmax else ppmin
                except:
                    ppmin, ppmax = 0.0, 0.0
                if max_budget is not None and ppmin > max_budget:
                    continue
                if min_budget is not None and ppmax < min_budget and ppmax > 0:
                    continue

            # Amenities matching
            proj_amenities_str = str(
                proj.get("Demo_Amenities_Display") or proj.get("Online_Confirmed_Amenities") or proj.get("Amenities") or ""
            ).lower()
            if amenities:
                matched_amen = all(a.lower() in proj_amenities_str for a in amenities)
                if not matched_amen:
                    continue

            # Format result
            price_display = proj.get("Demo_Project_Price_Range") or "Available on request"
            img_list = [
                u for u in [
                    proj.get("Exterior_Front_Image_URL"),
                    proj.get("Exterior_Second_Image_URL"),
                    proj.get("Interior_Living_Image_URL"),
                    proj.get("Interior_Bedroom_Image_URL"),
                ] if u and str(u).startswith("http")
            ]
            results.append({
                "project_id": proj_id,
                "project_name": proj.get("Project_Name"),
                "developer_name": proj.get("Developer_Name"),
                "city": proj.get("City"),
                "locality": proj.get("Locality"),
                "full_address": proj.get("Full_Address"),
                "project_type": proj.get("Project_Type"),
                "possession_status": proj.get("Possession_Status"),
                "amenities": proj.get("Demo_Amenities_Display") or proj.get("Amenities"),
                "price_range": price_display,
                "spoken_price_script": self.format_demo_price_script(proj.get("Demo_Project_Price_Range")),
                "demo_apartments_count": len(matching_apts) if matching_apts else len(apts),
                "sample_apartment": matching_apts[0] if matching_apts else (apts[0] if apts else None),
                "official_url": proj.get("Official_Project_Page_URL") or proj.get("Amenities_Official_Source_URL"),
                "images": {
                    "exterior_front": proj.get("Exterior_Front_Image_URL"),
                    "exterior_second": proj.get("Exterior_Second_Image_URL"),
                    "interior_living": proj.get("Interior_Living_Image_URL"),
                    "interior_bedroom": proj.get("Interior_Bedroom_Image_URL"),
                    "mode": proj.get("Image_Mode") or "DEMO_REPRESENTATIVE",
                    "disclaimer": "Representative demo image, not developer photograph",
                },
                "image_urls": img_list,
                "is_demo_mode": True,
            })

            if len(results) >= limit:
                break

        return results

    def format_demo_price_script(self, raw_price_range: Optional[str]) -> str:
        """
        Formats demo price strictly according to Step 3 specification:
        'For this demo, the estimated price is around {price_range}. The actual selling price may vary.'
        """
        if not raw_price_range or str(raw_price_range).strip() in ("", "None", "null", "N/A"):
            return "For this demo, estimated pricing information is being researched. The actual selling price may vary."

        clean_range = str(raw_price_range).strip()
        # Clean currency symbol redundancy for spoken clarity, but PRESERVE decimal points (e.g. 1.25 Cr)
        clean_range = re.sub(r"(?i)\b(inr|rs\.?)\b|[₹]", "", clean_range).strip()
        clean_range = re.sub(r"\s+", " ", clean_range)
        return f"For this demo, the estimated price is around {clean_range}. The actual selling price may vary."

    def get_property_details(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves complete details for a project_id, demo_apartment_id, or project name.
        """
        # 1. By Project_ID
        if identifier in self.projects:
            proj = self.projects[identifier]
            proj_id = identifier
        # 2. By Demo_Apartment_ID
        elif identifier in self.demo_apartments:
            apt = self.demo_apartments[identifier]
            proj_id = apt.get("Project_ID")
            proj = self.projects.get(proj_id, {})
        # 3. By Project Name lookup
        elif identifier.lower() in self.project_name_index:
            proj_id = self.project_name_index[identifier.lower()]
            proj = self.projects[proj_id]
        else:
            # Fuzzy match project name
            proj_id = None
            proj = None
            for p_name, p_id in self.project_name_index.items():
                if identifier.lower() in p_name or p_name in identifier.lower():
                    proj_id = p_id
                    proj = self.projects[p_id]
                    break

        if not proj:
            return None

        cfgs = self.project_configurations.get(proj_id, [])
        apts = self.project_demo_apartments.get(proj_id, [])
        gallery = self.get_property_gallery(proj_id)

        return {
            "project_id": proj_id,
            "project_name": proj.get("Project_Name"),
            "developer_name": proj.get("Developer_Name"),
            "city": proj.get("City"),
            "locality": proj.get("Locality"),
            "full_address": proj.get("Full_Address"),
            "project_overview": proj.get("Project_Overview"),
            "possession_status": proj.get("Possession_Status"),
            "rera_number": proj.get("RERA_Number"),
            "amenities": proj.get("Demo_Amenities_Display") or proj.get("Amenities"),
            "estimated_price_range": proj.get("Demo_Project_Price_Range"),
            "spoken_demo_price": self.format_demo_price_script(proj.get("Demo_Project_Price_Range")),
            "configurations": [
                {
                    "configuration_id": c.get("Configuration_ID"),
                    "bhk": c.get("BHK"),
                    "description": c.get("Configuration_Description"),
                    "estimated_price_range": c.get("Demo_Price_Range"),
                    "spoken_price": self.format_demo_price_script(c.get("Demo_Price_Range")),
                }
                for c in cfgs
            ],
            "demo_apartments": [
                {
                    "apartment_id": a.get("Demo_Apartment_ID"),
                    "variant": a.get("Apartment_Variant"),
                    "bhk": a.get("BHK_DEMO"),
                    "block": a.get("Block_DEMO"),
                    "unit": a.get("Unit_Number_DEMO"),
                    "area_sqft": a.get("Builtup_Area_Sqft_DEMO"),
                    "estimated_price": a.get("Spoken_Price_Range_DEMO"),
                    "spoken_price": self.format_demo_price_script(a.get("Spoken_Price_Range_DEMO")),
                }
                for a in apts[:5]
            ],
            "gallery": gallery,
            "is_demo_mode": True,
            "demo_disclaimer": "All apartment prices and unit variations are demo approximations. Not an official seller quote.",
        }

    def get_property_price(self, identifier: str, bhk: Optional[int] = None) -> Dict[str, Any]:
        """
        Retrieves the exact estimated price range for a property/apartment/BHK.
        Enforces demo disclaimer:
        'For this demo, the estimated price is around ... The actual selling price may vary.'
        """
        details = self.get_property_details(identifier)
        if not details:
            return {
                "success": False,
                "error": f"Property '{identifier}' not found in demo dataset.",
                "is_demo_mode": True,
            }

        # If specific BHK is requested, check matching configuration or demo apartment
        chosen_range = None
        chosen_entity = details["project_name"]

        if bhk is not None:
            # Check demo apartments first for exact BHK
            proj_id = details["project_id"]
            apts = self.project_demo_apartments.get(proj_id, [])
            for a in apts:
                if str(a.get("BHK_DEMO")) == str(bhk):
                    chosen_range = a.get("Spoken_Price_Range_DEMO") or a.get("Price_Min_INR_DEMO")
                    chosen_entity = f"{bhk}BHK at {details['project_name']}"
                    break

            # Fallback to configurations
            if not chosen_range:
                for c in details["configurations"]:
                    if str(c.get("bhk")) == str(bhk):
                        chosen_range = c.get("estimated_price_range")
                        chosen_entity = f"{bhk}BHK ({c.get('description')})"
                        break

        if not chosen_range:
            chosen_range = details["estimated_price_range"]

        spoken_script = self.format_demo_price_script(chosen_range)

        return {
            "success": True,
            "project_name": details["project_name"],
            "entity": chosen_entity,
            "bhk": bhk,
            "estimated_price_range": chosen_range,
            "spoken_price_script": spoken_script,
            "is_demo_mode": True,
            "demo_disclaimer": "Estimated demo pricing only, not an official quotation. Actual selling price may vary.",
        }

    def compare_properties(self, identifiers: List[str]) -> Dict[str, Any]:
        """Compares 2 to 5 properties side-by-side."""
        items = []
        for ident in identifiers[:5]:
            det = self.get_property_details(ident)
            if det:
                items.append({
                    "project_name": det["project_name"],
                    "developer": det["developer_name"],
                    "city": det["city"],
                    "locality": det["locality"],
                    "possession_status": det["possession_status"],
                    "estimated_price_range": det["estimated_price_range"],
                    "spoken_price": det["spoken_demo_price"],
                    "amenities": det["amenities"][:120] if det["amenities"] else "N/A",
                })

        return {
            "success": len(items) >= 2,
            "comparison_count": len(items),
            "properties": items,
            "is_demo_mode": True,
        }

    def search_faqs(self, query: str, project_id: Optional[str] = None, limit: int = 3) -> List[Dict[str, Any]]:
        """Searches real estate FAQs and terminology."""
        q_tokens = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
        matches = []

        pool = self.project_faqs.get(project_id, self.faqs) if project_id else self.faqs

        for faq in pool:
            q_text = str(faq.get("Customer_Question") or "").lower()
            ans_text = str(faq.get("Verified_Answer") or "").lower()
            kw_text = str(faq.get("Keywords") or "").lower()

            score = 0
            for t in q_tokens:
                if t in q_text:
                    score += 3
                if t in kw_text:
                    score += 2
                if t in ans_text:
                    score += 1

            if score > 0:
                matches.append((score, {
                    "faq_id": faq.get("FAQ_ID"),
                    "question": faq.get("Customer_Question"),
                    "answer": faq.get("Verified_Answer"),
                    "category": faq.get("FAQ_Category"),
                }))

        matches.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in matches[:limit]]

    def get_property_gallery(self, project_id: str) -> Dict[str, Any]:
        """
        Returns 4 representative images for the project if available.
        """
        return self.get_property_images(project_id)

    def get_property_images(self, identifier: str) -> Dict[str, Any]:
        """
        Retrieves 4 representative property images (Exterior Front, Exterior Second,
        Interior Living, Interior Bedroom) for a project ID or project name.
        Enforces clear demo disclaimer: 'Representative demo image, not official developer photograph'.
        """
        proj = None
        proj_id = None
        # 1. Exact match on Project_ID
        if identifier in self.projects:
            proj_id = identifier
            proj = self.projects[proj_id]
        elif identifier in self.all_projects:
            proj_id = identifier
            proj = self.all_projects[proj_id]
        # 2. Match by normalized project name
        elif identifier.lower() in self.project_name_index:
            proj_id = self.project_name_index[identifier.lower()]
            proj = self.projects.get(proj_id) or self.all_projects.get(proj_id)
        else:
            # 3. Substring match
            for name, pid in self.project_name_index.items():
                if identifier.lower() in name or name in identifier.lower():
                    proj_id = pid
                    proj = self.projects.get(pid) or self.all_projects.get(pid)
                    break

        if not proj:
            return {
                "success": False,
                "has_images": False,
                "project_name": identifier,
                "error": f"Property '{identifier}' not found in active dataset.",
                "images": [],
                "official_url": None,
                "message": f"I couldn't locate '{identifier}' in our portfolio. You can ask for projects in Gurugram, Bengaluru, Mumbai, or Pune.",
            }

        project_name = proj.get("Project_Name") or identifier
        city = proj.get("City") or ""
        locality = proj.get("Locality") or ""
        developer = proj.get("Developer_Name") or ""
        official_url = proj.get("Official_Project_Page_URL") or proj.get("Amenities_Official_Source_URL")

        # 4 representative images
        ext_front = proj.get("Exterior_Front_Image_URL")
        ext_second = proj.get("Exterior_Second_Image_URL")
        int_living = proj.get("Interior_Living_Image_URL")
        int_bed = proj.get("Interior_Bedroom_Image_URL")

        image_items = []
        if ext_front:
            image_items.append({
                "label": "Building Facade (Exterior Front)",
                "category": "Exterior Front",
                "url": ext_front,
                "description": f"Representative architecture and facade of {project_name}"
            })
        if ext_second:
            image_items.append({
                "label": "Community Entrance & Grounds",
                "category": "Exterior Community",
                "url": ext_second,
                "description": f"Representative landscaping and entrance grounds for {project_name}"
            })
        if int_living:
            image_items.append({
                "label": "Living Room & Lounge Area",
                "category": "Interior Living",
                "url": int_living,
                "description": f"Representative open living layout and natural lighting at {project_name}"
            })
        if int_bed:
            image_items.append({
                "label": "Master Bedroom Suite",
                "category": "Interior Bedroom",
                "url": int_bed,
                "description": f"Representative master bedroom aesthetic and finish for {project_name}"
            })

        # Fallback to demo apartment image or JSON assets if columns were empty
        if not image_items:
            apts = self.project_demo_apartments.get(proj_id, [])
            for a in apts:
                img = a.get("Image_URL")
                if img and str(img).startswith("http") and not any(it["url"] == img for it in image_items):
                    image_items.append({
                        "label": f"Representative Unit {a.get('Apartment_Variant') or ''}",
                        "category": "Interior",
                        "url": str(img),
                        "description": "Representative apartment layout"
                    })
                if len(image_items) >= 4:
                    break

        urls_only = [item["url"] for item in image_items]

        return {
            "success": True,
            "has_images": len(image_items) > 0,
            "project_id": proj_id,
            "project_name": project_name,
            "developer_name": developer,
            "city": city,
            "locality": locality,
            "total_images": len(image_items),
            "images": image_items,
            "image_urls": urls_only,
            "disclaimer": "Representative demo images, not official developer photographs",
            "image_mode": proj.get("Image_Mode") or "DEMO_REPRESENTATIVE",
            "image_source": proj.get("Image_Source") or "Curated Architectural Photography (Unsplash)",
            "official_url": official_url,
            "message": f"Displaying {len(image_items)} representative demo pictures for {project_name} in {city}.",
            "spoken_summary": f"I have brought up representative pictures of {project_name} on your screen, featuring the building facade, grounds, and living spaces.",
        }

    def get_dataset_summary(self, city_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Dynamically calculates verified project counts, unique cities, and representative image stats
        from the active dataset. Guarantees 100% grounded answers to questions about dataset scope.
        """
        total_projects = len(self.projects)
        city_counts: Dict[str, int] = {}
        city_developers: Dict[str, set] = {}
        city_bhk_types: Dict[str, set] = {}

        for pid, p in self.projects.items():
            c = str(p.get("City") or "Unknown").strip()
            city_counts[c] = city_counts.get(c, 0) + 1
            dev = str(p.get("Developer_Name") or "").strip()
            if dev:
                city_developers.setdefault(c, set()).add(dev)

        for cid, cfg in self.configurations.items():
            pid = str(cfg.get("Project_ID") or "")
            proj = self.projects.get(pid)
            if proj:
                c = str(proj.get("City") or "Unknown").strip()
                bhk = cfg.get("BHK")
                if bhk:
                    city_bhk_types.setdefault(c, set()).add(f"{bhk}BHK")

        unique_cities_count = len(city_counts)
        total_images = total_projects * 4

        # Specific city filter check
        if city_filter:
            matched_city = None
            q = city_filter.strip().lower()
            for c_name in city_counts.keys():
                if q in c_name.lower() or self._matches_location(q, c_name, "", ""):
                    matched_city = c_name
                    break

            if matched_city:
                cnt = city_counts[matched_city]
                devs = sorted(list(city_developers.get(matched_city, [])))[:4]
                bhks = sorted(list(city_bhk_types.get(matched_city, [])))
                dev_str = ", ".join(devs)
                return {
                    "success": True,
                    "city": matched_city,
                    "project_count": cnt,
                    "total_representative_images": cnt * 4,
                    "top_developers": devs,
                    "available_configurations": bhks,
                    "voice_summary": (
                        f"In {matched_city}, we have {cnt} verified projects in our portfolio, "
                        f"including developments by {dev_str}. We also have {cnt * 4} representative property images available."
                    ),
                }
            else:
                return {
                    "success": False,
                    "city": city_filter,
                    "error": f"City '{city_filter}' not found in active dataset.",
                    "available_cities": sorted(list(city_counts.keys())),
                    "voice_summary": (
                        f"We currently do not have listings in {city_filter}. Our active portfolio covers {unique_cities_count} cities, "
                        f"including Gurugram, Bengaluru, Mumbai, and Pune."
                    ),
                }

        # Overall summary
        top_cities = sorted(city_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        city_breakdown_str = ", ".join([f"{c}: {n} projects" for c, n in top_cities])

        return {
            "success": True,
            "total_actual_projects": total_projects,
            "total_unique_cities": unique_cities_count,
            "total_representative_images": total_images,
            "top_cities": [{"city": c, "project_count": n} for c, n in top_cities],
            "all_city_counts": city_counts,
            "voice_summary": (
                f"Our active real estate portfolio contains {total_projects} verified projects across {unique_cities_count} major Indian cities, "
                f"with {total_images} representative property images. Our largest selections are in {city_breakdown_str}."
            ),
        }
