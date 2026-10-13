/**
 * Типы Admin API — псевдонимы сгенерированной схемы OpenAPI.
 *
 * Руками здесь ничего не описывается: источник истины — Pydantic-схемы
 * backend, `schema.d.ts` генерируется из них. Псевдонимы нужны, потому
 * что FastAPI разводит одноимённые схемы витрины и админки по полным
 * путям модулей, и тащить такие имена в компоненты незачем.
 */

import type { components, operations } from '@oinau/api-types';

type Schemas = components['schemas'];

/** Query-параметры операции ровно в том виде, как их объявил backend. */
export type QueryOf<Operation extends keyof operations> = NonNullable<
  operations[Operation]['parameters']['query']
>;

// ------------------------------------------------------------ сотрудники
export type UserRole = Schemas['UserRole'];
export type TokenResponse = Schemas['TokenResponse'];
export type LoginRequest = Schemas['LoginRequest'];
export type CurrentUser = Schemas['CurrentUserRead'];
export type AdminUser = Schemas['UserRead'];
export type UserPage = Schemas['Page_UserRead_'];
export type UserCreate = Schemas['UserCreate'];
export type UserUpdate = Schemas['UserUpdate'];
export type RolePermissions = Schemas['RolePermissionsRead'];
export type UserListQuery = QueryOf<'list_users_api_v1_admin_users_get'>;
export type ChangePasswordRequest = Schemas['ChangePasswordRequest'];

// ----------------------------------------------------------------- товары
export type ProductStatus = Schemas['ProductStatus'];
export type ProductAdminSort = Schemas['ProductAdminSort'];
export type ProductListRow = Schemas['ProductListRow'];
export type ProductPage = Schemas['Page_ProductListRow_'];
export type ProductRead = Schemas['ProductRead'];
export type ProductCreate = Schemas['ProductCreate'];
export type ProductUpdate = Schemas['ProductUpdate'];
export type ProductTranslation = Schemas['ProductTranslationIn'];
export type ProductCategoryItem = Schemas['ProductCategoryItem'];
export type ProductCategoryRead = Schemas['ProductCategoryRead'];
export type ProductAttributeItem = Schemas['ProductAttributeItem'];
export type ProductAttributeRead = Schemas['ProductAttributeRead'];
export type ProductListQuery = QueryOf<'list_products_api_v1_admin_products_get'>;

// ------------------------------------------------------------- категории
export type CategoryRead = Schemas['CategoryRead'];
export type CategoryPage = Schemas['Page_CategoryRead_'];
export type CategoryTreeNode = Schemas['CategoryTreeNode'];
export type CategoryAttribute = Schemas['CategoryAttributeRead'];
export type CategoryAttributeItem = Schemas['CategoryAttributeItem'];
export type CategoryCreate = Schemas['CategoryCreate'];
export type CategoryUpdate = Schemas['CategoryUpdate'];
export type CategoryTranslation = Schemas['CategoryTranslationIn'];

// ------------------------------------------------------- характеристики
export type AttributeValueType = Schemas['AttributeValueType'];
export type AttributeRead = Schemas['AttributeRead'];
export type AttributeOption = Schemas['AttributeOptionRead'];
export type AttributePage = Schemas['Page_AttributeRead_'];
export type AttributeCreate = Schemas['AttributeCreate'];
export type AttributeUpdate = Schemas['AttributeUpdate'];
export type AttributeOptionCreate = Schemas['AttributeOptionCreate'];
export type AttributeOptionUpdate = Schemas['AttributeOptionUpdate'];
export type AttributeCategoryRef = Schemas['AttributeCategoryRef'];
export type AttributeListQuery = QueryOf<'list_attributes_api_v1_admin_attributes_get'>;

// ------------------------------------------------------------------ цены
export type PricingRead = Schemas['PricingRead'];
export type PricingUpdate = Schemas['PricingUpdate'];
export type PriceTierInput = Schemas['PriceTierInput'];
export type PriceTierRead = Schemas['app__modules__pricing__schemas_admin__PriceTierRead'];

// -------------------------------------------------------------- медиа
export type ImageKind = Schemas['ImageKind'];
export type MediaRead = Schemas['MediaRead'];
export type MediaDetail = Schemas['MediaDetail'];
export type MediaUploadCreated = Schemas['MediaUploadCreated'];
export type ProductImage = Schemas['ProductImageRead'];
export type ProductImageList = Schemas['ProductImageList'];

// ------------------------------------------------------------------ заявки
export type RequestStatus = Schemas['RequestStatus'];
export type RequestKind = Schemas['RequestKind'];
export type RequestSource = Schemas['RequestSource'];
export type RequestAdminSort = Schemas['RequestAdminSort'];
export type RequestListItem = Schemas['RequestListItem'];
export type RequestPage = Schemas['Page_RequestListItem_'];
export type RequestDetail = Schemas['RequestDetail'];
export type RequestItem = Schemas['RequestItemRead'];
export type RequestAttachment = Schemas['RequestAttachmentRead'];
export type RequestComment = Schemas['RequestCommentRead'];
export type RequestCommentCreate = Schemas['RequestCommentCreate'];
export type RequestStatusHistoryEntry = Schemas['RequestStatusHistoryRead'];
export type RequestStatusUpdate = Schemas['RequestStatusUpdate'];
export type Region = Schemas['RegionRead'];
export type RequestListQuery = QueryOf<'list_requests_api_v1_admin_requests_get'>;

// ------------------------------------------------------ сводка каталога
export type CatalogSummary = Schemas['CatalogSummaryRead'];

// ------------------------------------------------------------ остатки
export type StockSource = Schemas['StockSource'];
export type StockListSort = Schemas['StockListSort'];
export type ProductStock = Schemas['ProductStockRead'];
export type StockEntry = Schemas['StockEntryRead'];
export type StockUpdate = Schemas['StockUpdate'];
export type AvailabilityRead = Schemas['AvailabilityRead'];
export type ProductStockListItem = Schemas['ProductStockListItem'];
export type ProductStockPage = Schemas['Page_ProductStockListItem_'];
export type StockListQuery = QueryOf<'list_stock_api_v1_admin_stock_get'>;
// ----------------------------------------------------------------- цвета
export type Color = Schemas['ColorRead'];
export type ColorCreate = Schemas['ColorCreate'];
export type ColorUpdate = Schemas['ColorUpdate'];
export type ProductColors = Schemas['ProductColorsRead'];
export type ProductColor = Schemas['ProductColorRead'];
export type ProductColorsUpdate = Schemas['ProductColorsUpdate'];

export type Warehouse = Schemas['WarehouseRead'];
export type WarehouseCreate = Schemas['WarehouseCreate'];
export type WarehouseUpdate = Schemas['WarehouseUpdate'];
export type WarehousePage = Schemas['Page_WarehouseRead_'];
export type WarehouseListQuery = QueryOf<'list_warehouses_api_v1_admin_warehouses_get'>;

// ----------------------------------------------------------- интеграции
export type IntegrationStatus = Schemas['IntegrationStatus'];
export type IntegrationChannel = Schemas['ChannelStatus'];
export type IntegrationSyncSummary = Schemas['SyncSummary'];

// ---------------------------------------------------------------- аудит
export type AuditLogEntry = Schemas['AuditLogRead'];
export type AuditLogPage = Schemas['Page_AuditLogRead_'];
export type AuditLogQuery = QueryOf<'list_audit_log_api_v1_admin_audit_get'>;

// --------------------------------------------------------------- контент
export type ContentSectionKey = Schemas['ContentSectionKey'];
export type ContentSectionSummary = Schemas['ContentSectionSummary'];
export type SeoMeta = Schemas['SeoMeta'];
export type HomeContent = Schemas['HomeContent'];
export type HomeHero = Schemas['HomeHero'];
export type HomeAdvantage = Schemas['HomeAdvantage'];
export type HomeAbout = Schemas['HomeAbout'];
export type ContactsContent = Schemas['ContactsContent'];
export type ContactPhone = Schemas['ContactPhone'];
export type ContactEmail = Schemas['ContactEmail'];
export type WhatsappContact = Schemas['WhatsappContact'];
export type MapPoint = Schemas['MapPoint'];
export type DeliveryContent = Schemas['DeliveryContent'];
export type DeliveryMethod = Schemas['DeliveryMethod'];
export type FaqContent = Schemas['FaqContent'];
export type FaqItem = Schemas['FaqItem'];
export type RequisitesContent = Schemas['RequisitesContent'];
export type SiteSettingsContent = Schemas['SiteSettingsContent'];
export type ServicesContent = Schemas['ServicesContent'];
export type SocialLink = Schemas['SocialLink'];
export type SocialNetwork = Schemas['SocialNetwork'];
export type MediaPurpose = Schemas['MediaPurpose'];
export type MediaPage = Schemas['Page_MediaRead_'];
export type MediaListQuery = QueryOf<'list_media_api_v1_admin_media_get'>;

/** Ответ GET/PUT раздела: у каждого раздела своя схема `data`. */
export type ContentSectionReadMap = {
  home: Schemas['ContentSectionRead_HomeContent_'];
  contacts: Schemas['ContentSectionRead_ContactsContent_'];
  delivery: Schemas['ContentSectionRead_DeliveryContent_'];
  faq: Schemas['ContentSectionRead_FaqContent_'];
  requisites: Schemas['ContentSectionRead_RequisitesContent_'];
  settings: Schemas['ContentSectionRead_SiteSettingsContent_'];
  services: Schemas['ContentSectionRead_ServicesContent_'];
};
export type ContentSectionRead<K extends ContentSectionKey> = ContentSectionReadMap[K];
export type ContentSectionData<K extends ContentSectionKey> = ContentSectionReadMap[K]['data'];

// --------------------------------------------------- импорт / экспорт
export type ImportJob = Schemas['ImportJobListItem'];
export type ImportJobDetail = Schemas['ImportJobRead'];
export type ImportJobPage = Schemas['Page_ImportJobListItem_'];
export type ImportPreview = Schemas['ImportPreviewRead'];
export type ImportCommitResult = Schemas['ImportCommitRead'];
export type ImportIssue = Schemas['ImportIssueRead'];
export type ImportSummary = Schemas['ImportSummaryRead'];
export type ImportEntityCounts = Schemas['EntityCounts'];
export type ImportProductChange = Schemas['ProductChangeRead'];
export type ImportListQuery = QueryOf<'list_imports_api_v1_admin_catalog_imports_get'>;
export type BundleJob = Schemas['BundleJobRead'];
export type BundleUploadCreated = Schemas['BundleUploadCreated'];
export type BundleStats = Schemas['BundleStatsRead'];
export type BundleMediaStats = Schemas['BundleMediaStats'];

// ---------------------------------------------------------------- прочее
export type PricingType = Schemas['PricingType'];
export type PublicAvailability = Schemas['PublicAvailability'];
export type StockDisplayOverride = Schemas['StockDisplayOverride'];
export type MediaStatus = Schemas['MediaStatus'];
export type ImportJobStatus = Schemas['ImportJobStatus'];
