import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.semantic_models import (
    SemanticModelServiceError,
    create_next_draft,
    create_semantic_model,
    get_semantic_model,
    list_semantic_models,
    mapping_candidates,
    publish_semantic_model,
    update_semantic_draft,
)
from packages.platform_core.policy import Action
from packages.semantic_model.manufacturing import manufacturing_quality_template
from packages.shared_contracts.semantic_models import (
    MappingCandidateResponse,
    SemanticDraftUpdateRequest,
    SemanticModelCreateRequest,
    SemanticModelPage,
    SemanticModelResponse,
    SemanticVersionRequest,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/semantic-models", tags=["semantic-models"]
)


def _error(exc: SemanticModelServiceError) -> HTTPException:
    if exc.code.endswith("not_found"):
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "semantic_model.invalid_reference",
        "semantic_model.incomplete",
        "semantic_model.mapping_not_found",
        "semantic_model.mapping_unconfirmed",
    }:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        code = status.HTTP_409_CONFLICT
    return HTTPException(code, detail={"code": exc.code, "message": exc.message})


def _commit(db: DbSession) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "semantic_model.name_conflict",
                "message": "A semantic model with this name already exists",
            },
        ) from exc


@router.get("", response_model=SemanticModelPage)
def list_models(workspace_id: uuid.UUID, db: DbSession, user: CurrentUser) -> SemanticModelPage:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.SEMANTIC_READ)
    items = list_semantic_models(db, workspace_id=workspace_id)
    return SemanticModelPage(items=items, total=len(items))


@router.post("", response_model=SemanticModelResponse, status_code=status.HTTP_201_CREATED)
def create_model(
    workspace_id: uuid.UUID, payload: SemanticModelCreateRequest, db: DbSession, user: CurrentUser
) -> SemanticModelResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.SEMANTIC_MANAGE)
    result = create_semantic_model(
        db,
        workspace_id=workspace_id,
        actor_user_id=user.id,
        name=payload.name,
        description=payload.description,
    )
    _commit(db)
    return result


@router.post(
    "/manufacturing-template",
    response_model=SemanticModelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_template(
    workspace_id: uuid.UUID, payload: SemanticModelCreateRequest, db: DbSession, user: CurrentUser
) -> SemanticModelResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.SEMANTIC_MANAGE)
    result = create_semantic_model(
        db,
        workspace_id=workspace_id,
        actor_user_id=user.id,
        name=payload.name,
        description=payload.description,
        document=manufacturing_quality_template(),
    )
    _commit(db)
    return result


@router.get("/{model_id}", response_model=SemanticModelResponse)
def detail(
    workspace_id: uuid.UUID, model_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> SemanticModelResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.SEMANTIC_READ)
    try:
        return get_semantic_model(db, workspace_id=workspace_id, model_id=model_id)
    except SemanticModelServiceError as exc:
        raise _error(exc) from exc


@router.put("/{model_id}/draft", response_model=SemanticModelResponse)
def update_draft(
    workspace_id: uuid.UUID,
    model_id: uuid.UUID,
    payload: SemanticDraftUpdateRequest,
    db: DbSession,
    user: CurrentUser,
) -> SemanticModelResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.SEMANTIC_MANAGE)
    try:
        result = update_semantic_draft(
            db, workspace_id=workspace_id, model_id=model_id, actor_user_id=user.id, payload=payload
        )
    except SemanticModelServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    _commit(db)
    return result


@router.post("/{model_id}/publish", response_model=SemanticModelResponse)
def publish(
    workspace_id: uuid.UUID,
    model_id: uuid.UUID,
    payload: SemanticVersionRequest,
    db: DbSession,
    user: CurrentUser,
) -> SemanticModelResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.SEMANTIC_MANAGE)
    try:
        result = publish_semantic_model(
            db,
            workspace_id=workspace_id,
            model_id=model_id,
            actor_user_id=user.id,
            version=payload.version,
        )
    except SemanticModelServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    _commit(db)
    return result


@router.post("/{model_id}/new-draft", response_model=SemanticModelResponse)
def new_draft(
    workspace_id: uuid.UUID,
    model_id: uuid.UUID,
    payload: SemanticVersionRequest,
    db: DbSession,
    user: CurrentUser,
) -> SemanticModelResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.SEMANTIC_MANAGE)
    try:
        result = create_next_draft(
            db,
            workspace_id=workspace_id,
            model_id=model_id,
            actor_user_id=user.id,
            version=payload.version,
        )
    except SemanticModelServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    _commit(db)
    return result


@router.get("/{model_id}/mapping-candidates", response_model=MappingCandidateResponse)
def candidates(
    workspace_id: uuid.UUID,
    model_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    snapshot_id: uuid.UUID,
) -> MappingCandidateResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.SEMANTIC_READ)
    try:
        return mapping_candidates(
            db, workspace_id=workspace_id, model_id=model_id, snapshot_id=snapshot_id
        )
    except SemanticModelServiceError as exc:
        raise _error(exc) from exc
