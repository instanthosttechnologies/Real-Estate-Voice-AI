import io
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.company import Company
from app.models.user import User
from app.models.dataset import DynamicDataset, DynamicDatasetRecord
from app.schemas.dataset import (
    DatasetApprovalRequest,
    DatasetPreviewQueryRequest,
)
from app.services.dataset.inspector import inspect_dataset_workbook
from app.services.dataset.manager import upload_and_import_dataset
from app.api.v1.dataset_admin import (
    approve_dataset_schema_endpoint,
    activate_dataset_endpoint,
    preview_dataset_query_endpoint,
    get_currently_active_dataset,
    list_datasets,
    get_dataset_by_id,
    rollback_dataset_endpoint,
    list_available_companies,
    resolve_tenant_company,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def test_setup(db_session: Session):
    db = db_session

    # Create test companies
    comp_a = Company(id=uuid.uuid4(), name="Company Alpha")
    comp_b = Company(id=uuid.uuid4(), name="Company Beta")
    db.add_all([comp_a, comp_b])
    db.flush()

    # Create users
    super_owner = User(
        id=uuid.uuid4(),
        email="super@test.com",
        hashed_password="fake",
        role="super_owner",
        company_id=None,
    )
    admin_a = User(
        id=uuid.uuid4(),
        email="admin_a@test.com",
        hashed_password="fake",
        role="admin",
        company_id=comp_a.id,
    )
    admin_no_comp = User(
        id=uuid.uuid4(),
        email="unassigned@test.com",
        hashed_password="fake",
        role="admin",
        company_id=None,
    )
    db.add_all([super_owner, admin_a, admin_no_comp])
    db.commit()

    return {
        "db": db,
        "comp_a": comp_a,
        "comp_b": comp_b,
        "super_owner": super_owner,
        "admin_a": admin_a,
        "admin_no_comp": admin_no_comp,
    }


def test_dry_run_inspection(test_setup):
    csv_content = (
        b"vin,model,brand,price,mileage,transmission,confidential_dealer_margin\n"
        b"VIN101,Harrier,Tata,2200000,16.5,Automatic,150000\n"
        b"VIN102,XUV700,Mahindra,2400000,15.2,Automatic,180000\n"
    )

    res = inspect_dataset_workbook(csv_content, "cars.csv")
    meta = res["metadata_registry"]
    assert meta["filename"] == "cars.csv"
    assert meta["total_primary_rows"] == 2
    assert meta["primary_sheet"] in meta["worksheets"]
    cols = [c["column_name"] for c in meta["worksheets"][meta["primary_sheet"]]["columns"]]
    assert "vin" in cols
    assert "model" in cols
    assert "confidential_dealer_margin" in cols
    assert "vin" in res["candidate_identifiers"]


def test_full_dataset_workflow_and_preview_query(test_setup):
    db = test_setup["db"]
    admin_a = test_setup["admin_a"]

    # 1. Upload dataset (pending approval)
    csv_content = (
        b"sku,product_name,category,price,stock,supplier_cost\n"
        b"SKU-1,Ultra HD TV,Electronics,55000,20,38000\n"
        b"SKU-2,OLED Curved TV,Electronics,95000,8,68000\n"
        b"SKU-3,Soundbar 300W,Audio,18000,45,11000\n"
    )

    tenant_id = resolve_tenant_company(admin_a, db)
    dataset = upload_and_import_dataset(
        db=db,
        file_bytes=csv_content,
        filename="electronics.csv",
        company_id=tenant_id,
        user_id=admin_a.id,
        dataset_name="Consumer Electronics Inventory",
    )
    assert dataset.status == "pending_approval"
    assert dataset.is_active is False
    assert dataset.total_rows == 3
    dataset_id = dataset.id

    # 2. Cannot activate unapproved dataset (Fails closed)
    with pytest.raises(HTTPException) as exc_info:
        activate_dataset_endpoint(
            dataset_id=dataset_id,
            company_id=None,
            current_user=admin_a,
            db=db,
        )
    assert exc_info.value.status_code == 400
    assert "must be reviewed and approved" in exc_info.value.detail

    # 3. Admin schema review and approval (whitelisting public fields, excluding supplier_cost)
    approval_req = DatasetApprovalRequest(
        approved_fields=["sku", "product_name", "category", "price", "stock"],
        display_identifier="product_name",
        field_labels={
            "sku": "SKU Code",
            "product_name": "Product Name",
            "price": "Price in INR",
        },
        domain_name="Consumer Electronics Store",
        welcome_greeting="Welcome to Gadget World! How can I help you find audio and video electronics?",
    )
    approved = approve_dataset_schema_endpoint(
        dataset_id=dataset_id,
        req=approval_req,
        company_id=None,
        current_user=admin_a,
        db=db,
    )
    assert approved.status == "approved"
    assert "supplier_cost" not in approved.approved_fields
    assert approved.display_identifier == "product_name"
    assert approved.domain_name == "Consumer Electronics Store"

    # 4. Activate the dataset
    activated = activate_dataset_endpoint(
        dataset_id=dataset_id,
        company_id=None,
        current_user=admin_a,
        db=db,
    )
    assert activated.is_active is True
    assert activated.status == "active"

    # 5. Check active dataset endpoint
    active_resp = get_currently_active_dataset(
        company_id=None,
        current_user=admin_a,
        db=db,
    )
    assert active_resp is not None
    assert active_resp.id == dataset_id
    assert active_resp.domain_name == "Consumer Electronics Store"

    # 6. Execute Offline Preview Query (Zero Bedrock calls)
    preview_req = DatasetPreviewQueryRequest(
        query_text="OLED TV",
        limit=5,
    )
    preview_res = preview_dataset_query_endpoint(
        req=preview_req,
        company_id=None,
        current_user=admin_a,
        db=db,
    )
    assert preview_res.total_matches >= 1
    top_record = preview_res.records[0]
    assert "OLED" in top_record.display_title
    # Verify strict zero leakage of unapproved field:
    assert "supplier_cost" not in top_record.attributes
    assert "price" in top_record.attributes
    assert "Electronics" in preview_res.voice_grounding
    assert preview_res.dataset_name == "Consumer Electronics Inventory"

    # 7. Rollback endpoint
    rollback_res = rollback_dataset_endpoint(
        dataset_id=dataset_id,
        company_id=None,
        current_user=admin_a,
        db=db,
    )
    assert rollback_res["status"] == "rolled_back"


def test_tenant_isolation_fails_closed(test_setup):
    db = test_setup["db"]
    comp_b = test_setup["comp_b"]
    admin_no_comp = test_setup["admin_no_comp"]
    admin_a = test_setup["admin_a"]

    # Admin without company fails closed with 403 Forbidden
    with pytest.raises(HTTPException) as exc1:
        list_datasets(company_id=None, current_user=admin_no_comp, db=db)
    assert exc1.value.status_code == 403
    assert "not associated with an authorized tenant company" in exc1.value.detail

    # Admin A trying to access Company B datasets fails closed with 403 Forbidden
    with pytest.raises(HTTPException) as exc2:
        list_datasets(company_id=comp_b.id, current_user=admin_a, db=db)
    assert exc2.value.status_code == 403
    assert "Tenant isolation enforced" in exc2.value.detail


def test_super_owner_platform_and_companies_listing(test_setup):
    db = test_setup["db"]
    super_owner = test_setup["super_owner"]

    # Super Owner can view all companies
    companies = list_available_companies(current_user=super_owner, db=db)
    assert len(companies) == 2
    names = [c["name"] for c in companies]
    assert "Company Alpha" in names
    assert "Company Beta" in names

    # Super Owner can list datasets without hard fail when company_id is None
    datasets = list_datasets(company_id=None, current_user=super_owner, db=db)
    assert isinstance(datasets, list)
