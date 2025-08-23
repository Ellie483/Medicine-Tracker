from fastapi import APIRouter

router = APIRouter()

# Example route
@router.get("/medicine/test")
def test_route():
    return {"msg": "medicine router working"}
