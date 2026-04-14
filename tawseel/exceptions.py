"""
exceptions.py — أكواد الأخطاء والاستثناءات الخاصة بـ Tawseel API
Custom exceptions mapped to every TGA error code.
"""


class TawseelException(Exception):
    """Base exception for all Tawseel API errors."""

    def __init__(self, error_code: int, message_en: str, message_ar: str):
        self.error_code  = error_code
        self.message_en  = message_en
        self.message_ar  = message_ar
        super().__init__(f"[{error_code}] {message_en} | {message_ar}")

    @classmethod
    def from_error_code(cls, code: int) -> "TawseelException":
        """Factory: ينشئ الاستثناء المناسب بناءً على الكود."""
        return ERROR_MAP.get(code, UnknownTawseelError)(code)


# ─── أخطاء عامة ──────────────────────────────────────────────────────────────
class InternalServerError(TawseelException):
    def __init__(self, code=0):
        super().__init__(0, "Internal system error, please retry later", "خطأ داخلي، الرجاء إعادة المحاولة")

class NotFoundError(TawseelException):
    def __init__(self, code=2):
        super().__init__(2, "Driver or order not found", "لم يتم العثور على المندوب أو الطلب")

class InvalidCredentialError(TawseelException):
    def __init__(self, code=5):
        super().__init__(5, "Invalid username or password", "اسم المستخدم أو كلمة المرور خاطئة")

class UnknownTawseelError(TawseelException):
    def __init__(self, code=-1):
        super().__init__(code, "Unknown error", "خطأ غير معروف")


# ─── حقول مطلوبة ─────────────────────────────────────────────────────────────
class IdentityTypeIdRequired(TawseelException):
    def __init__(self, code=7):
        super().__init__(7, "Identity type ID is required", "نوع الهوية مطلوب")

class IdNumberRequired(TawseelException):
    def __init__(self, code=8):
        super().__init__(8, "ID number is required", "رقم الهوية مطلوب")

class DateOfBirthRequired(TawseelException):
    def __init__(self, code=9):
        super().__init__(9, "Date of birth is required", "تاريخ الميلاد مطلوب")

class RegistrationDateRequired(TawseelException):
    def __init__(self, code=10):
        super().__init__(10, "Registration date is required", "تاريخ التسجيل مطلوب")

class MobileRequired(TawseelException):
    def __init__(self, code=11):
        super().__init__(11, "Mobile number is required", "رقم الجوال مطلوب")

class RegionIdRequired(TawseelException):
    def __init__(self, code=12):
        super().__init__(12, "Region ID is required", "رقم المنطقة مطلوب")

class CityIdRequired(TawseelException):
    def __init__(self, code=13):
        super().__init__(13, "City ID is required", "رقم المدينة مطلوب")

class CarTypeRequired(TawseelException):
    def __init__(self, code=14):
        super().__init__(14, "Car type is required", "نوع المركبة مطلوب")

class CarNumberRequired(TawseelException):
    def __init__(self, code=15):
        super().__init__(15, "Car number is required", "رقم اللوحة مطلوب")


# ─── حقول غير صحيحة ──────────────────────────────────────────────────────────
class InvalidNationalityId(TawseelException):
    def __init__(self, code=16):
        super().__init__(16, "Invalid nationality ID", "الجنسية غير صحيحة")

class InvalidIdentityTypeId(TawseelException):
    def __init__(self, code=17):
        super().__init__(17, "Invalid identity type ID", "نوع الهوية غير صحيح")

class InvalidRegionId(TawseelException):
    def __init__(self, code=18):
        super().__init__(18, "Invalid region ID", "رقم المنطقة غير صحيح")

class InvalidCityId(TawseelException):
    def __init__(self, code=19):
        super().__init__(19, "Invalid city ID", "رقم المدينة غير صحيح")

class InvalidIdNumber(TawseelException):
    def __init__(self, code=20):
        super().__init__(20, "Invalid ID number", "رقم الهوية غير صحيح")

class InvalidDriverId(TawseelException):
    def __init__(self, code=21):
        super().__init__(21, "Invalid driver ID", "رقم المندوب غير صحيح")

class CityDoesntBelongToRegion(TawseelException):
    def __init__(self, code=22):
        super().__init__(22, "City does not belong to the selected region", "المدينة لا تنتمي للمنطقة")

class InvalidAuthorityId(TawseelException):
    def __init__(self, code=27):
        super().__init__(27, "Invalid authority ID", "رقم الجهة غير صحيح")

class InvalidCategoryId(TawseelException):
    def __init__(self, code=28):
        super().__init__(28, "Invalid category ID", "رقم تصنيف الطلب غير صحيح")

class InvalidOrderId(TawseelException):
    def __init__(self, code=29):
        super().__init__(29, "Order not found", "لم يتم العثور على الطلب")


# ─── منطق العمل ──────────────────────────────────────────────────────────────
class OrderCannotBeAccepted(TawseelException):
    def __init__(self, code=52):
        super().__init__(52, "Order cannot be accepted — status is not 'new'", "لا يمكن قبول الطلب لأن حالته ليست جديد")

class OrderCannotBeCanceled(TawseelException):
    def __init__(self, code=53):
        super().__init__(53, "Order cannot be canceled", "لا يمكن إلغاء الطلب")

class OrderNotAcceptedYet(TawseelException):
    def __init__(self, code=54):
        super().__init__(54, "Order must be accepted first", "يجب أن يتم قبول الطلب أولاً")

class DriverMustBeAssignedFirst(TawseelException):
    def __init__(self, code=57):
        super().__init__(57, "A driver must be assigned before executing", "يجب أولاً تعيين مندوب على الطلب")

class OrderNumberAlreadyCreatedToday(TawseelException):
    def __init__(self, code=58):
        super().__init__(58, "Order number already exists today", "رقم الطلب موجود بالفعل لهذا اليوم")

class DriverAlreadyExist(TawseelException):
    def __init__(self, code=47):
        super().__init__(47, "Driver already registered", "المندوب مسجل بالفعل")

class OrderCannotBeRejected(TawseelException):
    def __init__(self, code=77):
        super().__init__(77, "Order cannot be rejected", "لا يمكن رفض الطلب")

class IdNumberExpired(TawseelException):
    def __init__(self, code=80):
        super().__init__(80, "ID or residence card is expired", "بطاقة الهوية أو الإقامة منتهية")

class DriverYoungerThan18(TawseelException):
    def __init__(self, code=82):
        super().__init__(82, "Driver is younger than 18", "عمر المندوب أقل من 18 سنة")

class VehicleLicenseExpired(TawseelException):
    def __init__(self, code=87):
        super().__init__(87, "Vehicle license is expired", "استمارة المركبة منتهية")

class DrivingLicenseExpired(TawseelException):
    def __init__(self, code=90):
        super().__init__(90, "Driving license is expired", "رخصة القيادة منتهية")

class DriverSuspendedByTGA(TawseelException):
    def __init__(self, code=123):
        super().__init__(123, "Driver suspended by TGA", "السائق موقوف من قبل الهيئة العامة للنقل")

class DriverHasNoVehicle(TawseelException):
    def __init__(self, code=124):
        super().__init__(124, "Driver has no vehicle", "السائق لا يملك مركبة")


# ─── أخطاء Recovery ───────────────────────────────────────────────────────────
class InvalidBulkFileTemplate(TawseelException):
    def __init__(self, code=99):
        super().__init__(99, "Invalid file format or content", "محتوى الملف أو صيغته غير صالحة")

class InvalidBulkUUID(TawseelException):
    def __init__(self, code=100):
        super().__init__(100, "Invalid UUID", "معرف غير صالح")

class RecoveryServiceDisabled(TawseelException):
    def __init__(self, code=101):
        super().__init__(101, "Recovery service is disabled", "خدمة الاستعادة معطلة")

class IllegalNumberOfRows(TawseelException):
    def __init__(self, code=103):
        super().__init__(103, "File contains illegal number of rows (1-1000)", "عدد الصفوف في الملف غير صحيح")

class StillProcessing(TawseelException):
    def __init__(self, code=104):
        super().__init__(104, "File is still being processed", "الملف لايزال تحت المعالجة")


# ─── خريطة الأكواد ───────────────────────────────────────────────────────────
ERROR_MAP: dict = {
    0:   InternalServerError,
    2:   NotFoundError,
    5:   InvalidCredentialError,
    7:   IdentityTypeIdRequired,
    8:   IdNumberRequired,
    9:   DateOfBirthRequired,
    10:  RegistrationDateRequired,
    11:  MobileRequired,
    12:  RegionIdRequired,
    13:  CityIdRequired,
    14:  CarTypeRequired,
    15:  CarNumberRequired,
    16:  InvalidNationalityId,
    17:  InvalidIdentityTypeId,
    18:  InvalidRegionId,
    19:  InvalidCityId,
    20:  InvalidIdNumber,
    21:  InvalidDriverId,
    22:  CityDoesntBelongToRegion,
    27:  InvalidAuthorityId,
    28:  InvalidCategoryId,
    29:  InvalidOrderId,
    47:  DriverAlreadyExist,
    52:  OrderCannotBeAccepted,
    53:  OrderCannotBeCanceled,
    54:  OrderNotAcceptedYet,
    57:  DriverMustBeAssignedFirst,
    58:  OrderNumberAlreadyCreatedToday,
    77:  OrderCannotBeRejected,
    80:  IdNumberExpired,
    82:  DriverYoungerThan18,
    87:  VehicleLicenseExpired,
    90:  DrivingLicenseExpired,
    99:  InvalidBulkFileTemplate,
    100: InvalidBulkUUID,
    101: RecoveryServiceDisabled,
    103: IllegalNumberOfRows,
    104: StillProcessing,
    123: DriverSuspendedByTGA,
    124: DriverHasNoVehicle,
}
