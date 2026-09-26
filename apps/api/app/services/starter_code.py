from __future__ import annotations

import json
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..models import Project, ReviewStatus
from .project_identity import business_project_name


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "sap-project"


def _namespace(value: str) -> str:
    part = re.sub(r"[^a-z0-9]", "", value.lower())[:24] or "project"
    return f"com.sap.copilot.{part}"


def _abap_suffix(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())[:18] or "PROJECT"


def _requirements(project: Project) -> list[dict]:
    locators = {chunk.id: chunk.locator for chunk in getattr(getattr(project, "document", None), "chunks", [])}
    result = []
    for requirement in sorted(
        (item for item in (project.requirements or []) if item.review_status == ReviewStatus.approved),
        key=lambda item: item.requirement_key,
    ):
        result.append({
            "requirementKey": requirement.requirement_key,
            "title": requirement.title,
            "statement": requirement.statement,
            "type": requirement.requirement_type,
            "priority": requirement.priority,
            "acceptanceCriteria": requirement.acceptance_criteria,
            "sourceLocator": "; ".join(locators.get(chunk_id, "") for chunk_id in requirement.source_chunk_ids),
            "sourceQuote": requirement.source_quote,
            "implementationStatus": "TODO",
        })
    return result


def _artifact_document(project: Project, kind: str) -> dict | None:
    artifact = next((item for item in (project.artifacts or []) if item.kind == kind), None)
    if not artifact or artifact.status != "generated":
        return None
    document = (artifact.payload or {}).get("document")
    return document if isinstance(document, dict) else None


def _clean_text(val: str | None) -> str:
    return re.sub(r"\s+", " ", str(val or "")).strip()


def build_starter_code_zip(project: Project, artifact_root: str) -> dict:
    requirements = _requirements(project)
    if not requirements:
        raise ValueError("Approve at least one requirement before generating starter code")

    display_name = business_project_name(project)
    slug = _slug(project.name)
    namespace = _namespace(project.name)
    namespace_path = namespace.replace(".", "/")
    suffix = _abap_suffix(project.name)
    root_name = f"{slug}-sap-starter-code"

    output_dir = (Path(artifact_root) / project.id).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{root_name}.zip"
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    fsd = _artifact_document(project, "fsd") or {}
    brd_payload = getattr(getattr(project, "brd_knowledge", None), "payload", {}) or {}
    screens = fsd.get("screens") or brd_payload.get("screens") or []
    process_steps = fsd.get("process_steps") or brd_payload.get("process_steps") or []
    business_rules = fsd.get("business_rules") or brd_payload.get("business_rules") or []

    # ABAP Object Identifiers
    cds_root = f"ZI_{suffix}_R"[:30]
    cds_item = f"ZI_{suffix}Item_R"[:30]
    cds_proj = f"ZC_{suffix}_C"[:30]
    cds_item_proj = f"ZC_{suffix}Item_C"[:30]
    mde_name = f"ZC_{suffix}_C"[:30]
    bdef_name = cds_root
    behavior_class = f"ZBP_I_{suffix}_R"[:30]
    service_def = f"ZUI_{suffix}_O4"[:30]
    auth_class = f"ZCL_{suffix}_AUTH"[:30]
    interface_name = f"ZIF_{suffix}_SERVICE"[:30]
    class_name = f"ZCL_{suffix}_SERVICE"[:30]

    # 1. UI5 Manifest
    manifest = {
        "_version": "1.58.0",
        "sap.app": {
            "id": namespace,
            "type": "application",
            "i18n": "i18n/i18n.properties",
            "title": "{{appTitle}}",
            "description": "{{appDescription}}",
            "applicationVersion": {"version": "1.0.0"},
            "dataSources": {
                "mainService": {
                    "uri": f"/sap/opu/odata4/sap/{service_def.lower()}/srvd/sap/{service_def.lower()}/0001/",
                    "type": "OData",
                    "settings": {"odataVersion": "4.0"},
                },
                "mockData": {
                    "uri": "model/mockData.json",
                    "type": "JSON",
                },
            },
        },
        "sap.ui": {
            "technology": "UI5",
            "deviceTypes": {"desktop": True, "tablet": True, "phone": True},
        },
        "sap.ui5": {
            "dependencies": {
                "minUI5Version": "1.120.0",
                "libs": {
                    "sap.ui.core": {},
                    "sap.m": {},
                    "sap.f": {},
                    "sap.tnt": {},
                    "sap.ui.layout": {},
                    "sap.uxap": {},
                },
            },
            "contentDensities": {"compact": True, "cozy": True},
            "rootView": {
                "viewName": f"{namespace}.view.App",
                "type": "XML",
                "id": "appRoot",
                "async": True,
            },
            "models": {
                "i18n": {
                    "type": "sap.ui.model.resource.ResourceModel",
                    "settings": {"bundleName": f"{namespace}.i18n.i18n", "async": True},
                },
                "": {
                    "type": "sap.ui.model.json.JSONModel",
                    "uri": "model/mockData.json",
                },
            },
            "resources": {"css": [{"uri": "css/style.css"}]},
            "routing": {
                "config": {
                    "routerClass": "sap.m.routing.Router",
                    "viewType": "XML",
                    "viewPath": f"{namespace}.view",
                    "controlId": "pageContainer",
                    "controlAggregation": "pages",
                    "async": True,
                },
                "routes": [
                    {"name": "listReport", "pattern": "", "target": "targetListReport"},
                    {"name": "requestEntry", "pattern": "request/{poNumber}", "target": "targetRequestEntry"},
                    {"name": "requestTracking", "pattern": "tracking", "target": "targetRequestTracking"},
                    {"name": "approvalInbox", "pattern": "inbox", "target": "targetApprovalInbox"},
                    {"name": "passDownload", "pattern": "download/{passId}", "target": "targetPassDownload"},
                    {"name": "gateVerification", "pattern": "verification", "target": "targetGateVerification"},
                ],
                "targets": {
                    "targetListReport": {"viewName": "ListReport", "viewLevel": 1},
                    "targetRequestEntry": {"viewName": "RequestEntry", "viewLevel": 2},
                    "targetRequestTracking": {"viewName": "RequestTracking", "viewLevel": 2},
                    "targetApprovalInbox": {"viewName": "ApprovalInbox", "viewLevel": 1},
                    "targetPassDownload": {"viewName": "PassDownload", "viewLevel": 3},
                    "targetGateVerification": {"viewName": "GateVerification", "viewLevel": 1},
                },
            },
        },
    }

    # 2. Package.json
    package_json = {
        "name": f"@sap-copilot/{slug}-fiori",
        "version": "1.0.0",
        "private": True,
        "description": f"End-to-End SAP Fiori application for {display_name} generated from BRD & FSD",
        "engines": {"node": "^20.11.0 || >=22.0.0", "npm": ">=8"},
        "scripts": {
            "start": "ui5 serve --open index.html",
            "build": "ui5 build --all --clean-dest",
            "lint": "ui5lint",
            "test": "ui5 serve --open test/unit/unitTests.qunit.html",
        },
        "devDependencies": {
            "@ui5/cli": "^4.0.52",
            "@ui5/linter": "^1.20.18",
        },
    }

    # 3. UI5 YAML
    ui5_yaml = f'''specVersion: "4.0"
metadata:
  name: "{namespace}"
type: application
framework:
  name: SAPUI5
  version: "1.120.0"
  libraries:
    - name: sap.f
    - name: sap.m
    - name: sap.tnt
    - name: sap.ui.core
    - name: sap.ui.layout
    - name: sap.uxap
    - name: themelib_sap_horizon
'''

    # 4. App Shell View (ToolPage with SideNavigation)
    app_view = f'''<mvc:View
  controllerName="{namespace}.controller.App"
  xmlns:mvc="sap.ui.core.mvc"
  xmlns="sap.m"
  xmlns:tnt="sap.tnt">
  <tnt:ToolPage id="toolPage">
    <tnt:header>
      <tnt:ToolHeader>
        <Button id="sideNavToggleBtn" icon="sap-icon://menu2" type="Transparent" press=".onSideNavButtonPress">
          <layoutData><OverflowToolbarLayoutData priority="NeverOverflow"/></layoutData>
        </Button>
        <Avatar src="sap-icon://sap-box" displaySize="XS" displayShape="Square" class="sapUiTinyMarginBegin"/>
        <Title text="{display_name}" level="H2"/>
        <ToolbarSpacer/>
        <tnt:InfoLabel text="SAP Fiori Horizon" colorScheme="8"/>
        <Button icon="sap-icon://bell" type="Transparent"/>
        <Avatar initials="SC" displaySize="XS" tooltip="SAP Copilot User"/>
      </tnt:ToolHeader>
    </tnt:header>
    <tnt:sideContent>
      <tnt:SideNavigation id="sideNavigation" selectedKey="listReport" itemSelect=".onNavItemSelect">
        <tnt:NavigationList>
          <tnt:NavigationListItem text="Purchase Orders (List)" icon="sap-icon://list" key="listReport"/>
          <tnt:NavigationListItem text="Request Entry (Form)" icon="sap-icon://create-form" key="requestEntry"/>
          <tnt:NavigationListItem text="Request Tracking" icon="sap-icon://history" key="requestTracking"/>
          <tnt:NavigationListItem text="Approver Inbox (L1/L2)" icon="sap-icon://inbox" key="approvalInbox"/>
          <tnt:NavigationListItem text="Approved Pass Download" icon="sap-icon://pdf-attachment" key="passDownload"/>
          <tnt:NavigationListItem text="Gate Security Scanner" icon="sap-icon://qr-code" key="gateVerification"/>
        </tnt:NavigationList>
      </tnt:SideNavigation>
    </tnt:sideContent>
    <tnt:mainContents>
      <NavContainer id="pageContainer"/>
    </tnt:mainContents>
  </tnt:ToolPage>
</mvc:View>
'''

    app_controller = f'''sap.ui.define([
  "sap/ui/core/mvc/Controller"
], function (Controller) {{
  "use strict";

  return Controller.extend("{namespace}.controller.App", {{
    onInit: function () {{
      this.getOwnerComponent().getRouter().initialize();
    }},

    onSideNavButtonPress: function () {{
      var oToolPage = this.byId("toolPage");
      oToolPage.setSideExpanded(!oToolPage.getSideExpanded());
    }},

    onNavItemSelect: function (oEvent) {{
      var sKey = oEvent.getParameter("item").getKey();
      var oRouter = this.getOwnerComponent().getRouter();
      if (sKey === "listReport") {{
        oRouter.navTo("listReport");
      }} else if (sKey === "requestEntry") {{
        oRouter.navTo("requestEntry", {{ poNumber: "4500019280" }});
      }} else if (sKey === "requestTracking") {{
        oRouter.navTo("requestTracking");
      }} else if (sKey === "approvalInbox") {{
        oRouter.navTo("approvalInbox");
      }} else if (sKey === "passDownload") {{
        oRouter.navTo("passDownload", {{ passId: "GP-2026-0041" }});
      }} else if (sKey === "gateVerification") {{
        oRouter.navTo("gateVerification");
      }}
    }}
  }});
}});
'''

    # 5. List Report View (SCR-01: Supplier Purchase Orders)
    list_report_view = f'''<mvc:View
  controllerName="{namespace}.controller.ListReport"
  xmlns:mvc="sap.ui.core.mvc"
  xmlns="sap.m"
  xmlns:f="sap.f"
  xmlns:fb="sap.ui.comp.filterbar"
  xmlns:core="sap.ui.core">
  <f:DynamicPage headerExpanded="true" showFooter="false">
    <f:title>
      <f:DynamicPageTitle>
        <f:heading>
          <Title text="Eligible Purchase Orders (SCR-01)"/>
        </f:heading>
        <f:expandedContent>
          <Text text="Search and select released purchase orders eligible for gate pass entry"/>
        </f:expandedContent>
        <f:actions>
          <Button text="Create Request" type="Emphasized" icon="sap-icon://add" press=".onCreateRequestPress"/>
          <Button text="Export" icon="sap-icon://excel-attachment" press=".onExportPress"/>
          <Button icon="sap-icon://refresh" press=".onRefreshPress"/>
        </f:actions>
      </f:DynamicPageTitle>
    </f:title>
    <f:header>
      <f:DynamicPageHeader pinnable="true">
        <fb:FilterBar id="filterBar" search=".onSearch" showClearOnFB="true">
          <fb:filterGroupItems>
            <fb:FilterGroupItem name="poNumber" label="PO Number" groupName="G1" visibleInFilterBar="true">
              <fb:control>
                <SearchField id="searchPONumber" placeholder="e.g. 4500019280" search=".onSearch"/>
              </fb:control>
            </fb:FilterGroupItem>
            <fb:FilterGroupItem name="plant" label="Receiving Plant" groupName="G1" visibleInFilterBar="true">
              <fb:control>
                <Select id="filterPlant" change=".onSearch">
                  <core:Item key="" text="All Plants"/>
                  <core:Item key="1000" text="1000 - Chakan Main Plant"/>
                  <core:Item key="1010" text="1010 - Talegaon Plant"/>
                </Select>
              </fb:control>
            </fb:FilterGroupItem>
            <fb:FilterGroupItem name="status" label="Status" groupName="G1" visibleInFilterBar="true">
              <fb:control>
                <Select id="filterStatus" change=".onSearch">
                  <core:Item key="" text="All Statuses"/>
                  <core:Item key="Eligible" text="Eligible - Released"/>
                  <core:Item key="Pass Requested" text="Pass Requested"/>
                </Select>
              </fb:control>
            </fb:FilterGroupItem>
          </fb:filterGroupItems>
        </fb:FilterBar>
      </f:DynamicPageHeader>
    </f:header>
    <f:content>
      <Table id="poTable" items="{{/purchaseOrders}}" mode="SingleSelectMaster" selectionChange=".onPOSelectionChange" growing="true" growingThreshold="20">
        <headerToolbar>
          <OverflowToolbar>
            <Title text="Open Orders ({{= ${{/purchaseOrders}}.length }})" level="H3"/>
            <ToolbarSpacer/>
            <SearchField width="240px" placeholder="Quick search..." liveChange=".onQuickSearch"/>
          </OverflowToolbar>
        </headerToolbar>
        <columns>
          <Column width="11rem"><Text text="PO Number"/></Column>
          <Column minScreenWidth="Tablet" demandPopin="true"><Text text="Supplier"/></Column>
          <Column minScreenWidth="Tablet" demandPopin="true"><Text text="Delivery Date"/></Column>
          <Column width="7rem"><Text text="Plant"/></Column>
          <Column width="6rem" hAlign="End"><Text text="Items"/></Column>
          <Column width="9rem" hAlign="End"><Text text="Open Net Value"/></Column>
          <Column width="10rem" hAlign="Center"><Text text="Pass Status"/></Column>
          <Column width="7rem" hAlign="Center"><Text text="Action"/></Column>
        </columns>
        <items>
          <ColumnListItem type="Navigation" press=".onRowPress">
            <cells>
              <ObjectIdentifier title="{{poNumber}}" text="Type: NB Standard"/>
              <Text text="{{supplierName}} ({{supplierCode}})"/>
              <Text text="{{deliveryDate}}"/>
              <Text text="{{plant}}"/>
              <Text text="{{itemCount}} items"/>
              <ObjectNumber number="{{openValue}}" unit="{{currency}}"/>
              <ObjectStatus text="{{status}}" state="{{statusState}}"/>
              <Button text="Select" type="Transparent" press=".onSelectRowBtnPress"/>
            </cells>
          </ColumnListItem>
        </items>
      </Table>
    </f:content>
  </f:DynamicPage>
</mvc:View>
'''

    list_report_controller = f'''sap.ui.define([
  "sap/ui/core/mvc/Controller",
  "sap/ui/model/Filter",
  "sap/ui/model/FilterOperator",
  "sap/m/MessageToast"
], function (Controller, Filter, FilterOperator, MessageToast) {{
  "use strict";

  return Controller.extend("{namespace}.controller.ListReport", {{
    onRowPress: function (oEvent) {{
      var oContext = oEvent.getSource().getBindingContext();
      var sPONumber = oContext.getProperty("poNumber");
      this.getOwnerComponent().getRouter().navTo("requestEntry", {{ poNumber: sPONumber }});
    }},

    onSelectRowBtnPress: function (oEvent) {{
      var oContext = oEvent.getSource().getBindingContext();
      var sPONumber = oContext.getProperty("poNumber");
      this.getOwnerComponent().getRouter().navTo("requestEntry", {{ poNumber: sPONumber }});
    }},

    onCreateRequestPress: function () {{
      var oTable = this.byId("poTable");
      var oSelectedItem = oTable.getSelectedItem();
      if (!oSelectedItem) {{
        MessageToast.show("Please select a purchase order row from the table first");
        return;
      }}
      var sPONumber = oSelectedItem.getBindingContext().getProperty("poNumber");
      this.getOwnerComponent().getRouter().navTo("requestEntry", {{ poNumber: sPONumber }});
    }},

    onQuickSearch: function (oEvent) {{
      var sQuery = oEvent.getParameter("newValue");
      var aFilters = [];
      if (sQuery && sQuery.length > 0) {{
        aFilters.push(new Filter({{
          filters: [
            new Filter("poNumber", FilterOperator.Contains, sQuery),
            new Filter("supplierName", FilterOperator.Contains, sQuery),
            new Filter("plant", FilterOperator.Contains, sQuery)
          ],
          and: false
        }}));
      }}
      this.byId("poTable").getBinding("items").filter(aFilters);
    }},

    onSearch: function () {{
      MessageToast.show("Filtered purchase order worklist");
    }},

    onExportPress: function () {{
      MessageToast.show("Exporting PO list to Excel");
    }},

    onRefreshPress: function () {{
      this.getView().getModel().refresh(true);
      MessageToast.show("Worklist refreshed from SAP backend");
    }}
  }});
}});
'''

    # 6. Request Entry View (SCR-02: PO Object Page & Gate Pass Request Entry Form)
    request_entry_view = f'''<mvc:View
  controllerName="{namespace}.controller.RequestEntry"
  xmlns:mvc="sap.ui.core.mvc"
  xmlns="sap.m"
  xmlns:uxap="sap.uxap"
  xmlns:layout="sap.ui.layout"
  xmlns:form="sap.ui.layout.form"
  xmlns:core="sap.ui.core">
  <uxap:ObjectPageLayout id="objectPageLayout" showTitleInHeaderContent="true" showEditHeaderButton="false">
    <uxap:headerTitle>
      <uxap:ObjectPageDynamicHeaderTitle>
        <uxap:expandedHeading>
          <Title text="Gate Pass Request — PO {{/activeRequest/poNumber}}" wrapping="true"/>
        </uxap:expandedHeading>
        <uxap:snappedHeading>
          <Title text="PO {{/activeRequest/poNumber}} — Request Entry" wrapping="true"/>
        </uxap:snappedHeading>
        <uxap:expandedContent>
          <Text text="Supplier: {{/activeRequest/supplierName}} ({{/activeRequest/supplierCode}})"/>
        </uxap:expandedContent>
        <uxap:actions>
          <Button text="Validate &amp; Submit" type="Emphasized" icon="sap-icon://paper-plane" press=".onSubmitRequest"/>
          <Button text="Save Draft" type="Default" icon="sap-icon://save" press=".onSaveDraft"/>
          <Button text="Cancel" type="Transparent" press=".onNavBack"/>
        </uxap:actions>
      </uxap:ObjectPageDynamicHeaderTitle>
    </uxap:headerTitle>
    <uxap:headerContent>
      <layout:HorizontalLayout allowWrapping="true">
        <layout:VerticalLayout class="sapUiMediumMarginEnd">
          <ObjectStatus title="Purchasing Org" text="{{/activeRequest/purchasingOrg}}"/>
          <ObjectStatus title="Company Code" text="{{/activeRequest/companyCode}}"/>
        </layout:VerticalLayout>
        <layout:VerticalLayout class="sapUiMediumMarginEnd">
          <ObjectStatus title="Target Plant" text="{{/activeRequest/plant}}"/>
          <ObjectStatus title="Order Value" text="{{/activeRequest/openValue}} {{/activeRequest/currency}}"/>
        </layout:VerticalLayout>
        <layout:VerticalLayout>
          <ObjectStatus title="Processing State" text="Draft Entry" state="Information"/>
        </layout:VerticalLayout>
      </layout:HorizontalLayout>
    </uxap:headerContent>
    <uxap:sections>
      <uxap:ObjectPageSection title="Vehicle &amp; Driver Details">
        <uxap:subSections>
          <uxap:ObjectPageSubSection>
            <form:SimpleForm editable="true" layout="ResponsiveGridLayout" labelSpanXL="4" labelSpanL="4" labelSpanM="4" columnsXL="2" columnsL="2" columnsM="1">
              <core:Title text="Vehicle Registration &amp; Identification"/>
              <Label text="Vehicle Number" required="true"/>
              <Input id="inputVehicle" value="{{/activeRequest/vehicleNumber}}" placeholder="e.g. MH-12-AB-1234"/>
              <Label text="Delivery Note / Challan No" required="true"/>
              <Input id="inputChallan" value="{{/activeRequest/deliveryNote}}" placeholder="e.g. DN-2026-9901"/>
              
              <core:Title text="Driver / Transporter Information"/>
              <Label text="Driver Full Name" required="true"/>
              <Input id="inputDriver" value="{{/activeRequest/driverName}}" placeholder="e.g. Ramesh Kumar"/>
              <Label text="Driver Mobile Number" required="true"/>
              <Input id="inputMobile" value="{{/activeRequest/driverMobile}}" type="Tel" placeholder="10-digit mobile number"/>
              <Label text="Additional Persons Count"/>
              <StepInput value="{{/activeRequest/additionalPersons}}" min="0" max="5"/>
            </form:SimpleForm>
          </uxap:ObjectPageSubSection>
        </uxap:subSections>
      </uxap:ObjectPageSection>

      <uxap:ObjectPageSection title="Schedule &amp; Entry Slot">
        <uxap:subSections>
          <uxap:ObjectPageSubSection>
            <form:SimpleForm editable="true" layout="ResponsiveGridLayout" labelSpanXL="4" labelSpanL="4" labelSpanM="4" columnsXL="2" columnsL="2" columnsM="1">
              <core:Title text="Visit Logistics"/>
              <Label text="Requested Entry Date" required="true"/>
              <DatePicker id="inputEntryDate" value="{{/activeRequest/requestedEntryDate}}" valueFormat="yyyy-MM-dd" displayFormat="yyyy-MM-dd"/>
              <Label text="Expected Time Slot" required="true"/>
              <Select id="selectTimeSlot" selectedKey="{{/activeRequest/timeSlot}}">
                <core:Item key="SLOT-01" text="Morning: 08:00 - 12:00"/>
                <core:Item key="SLOT-02" text="Afternoon: 12:00 - 16:00"/>
                <core:Item key="SLOT-03" text="Evening: 16:00 - 20:00"/>
              </Select>
              
              <core:Title text="Location &amp; Purpose"/>
              <Label text="Designated Gate / Bay"/>
              <Select selectedKey="{{/activeRequest/gateBay}}">
                <core:Item key="GATE-01" text="Gate 1 - Material Inward (North)"/>
                <core:Item key="GATE-02" text="Gate 2 - Heavy Logistics (East)"/>
              </Select>
              <Label text="Purpose of Visit"/>
              <TextArea value="{{/activeRequest/purpose}}" rows="2" placeholder="Material delivery against scheduled PO lines"/>
              <Label text="Remarks / Instructions"/>
              <TextArea value="{{/activeRequest/remarks}}" rows="2" placeholder="Unloading dock requirements, PPE compliance, etc."/>
            </form:SimpleForm>
          </uxap:ObjectPageSubSection>
        </uxap:subSections>
      </uxap:ObjectPageSection>

      <uxap:ObjectPageSection title="PO Items for Inward">
        <uxap:subSections>
          <uxap:ObjectPageSubSection>
            <Table items="{{/activeRequest/items}}">
              <columns>
                <Column width="5rem"><Text text="Item"/></Column>
                <Column><Text text="Material Description"/></Column>
                <Column width="8rem" hAlign="End"><Text text="PO Qty"/></Column>
                <Column width="8rem" hAlign="End"><Text text="Delivery Qty"/></Column>
                <Column width="5rem"><Text text="Unit"/></Column>
              </columns>
              <items>
                <ColumnListItem>
                  <cells>
                    <Text text="{{itemNumber}}"/>
                    <ObjectIdentifier title="{{materialName}}" text="{{materialCode}}"/>
                    <Text text="{{poQty}}"/>
                    <Input value="{{deliveryQty}}" type="Number"/>
                    <Text text="{{unit}}"/>
                  </cells>
                </ColumnListItem>
              </items>
            </Table>
          </uxap:ObjectPageSubSection>
        </uxap:subSections>
      </uxap:ObjectPageSection>
    </uxap:sections>
  </uxap:ObjectPageLayout>
</mvc:View>
'''

    request_entry_controller = f'''sap.ui.define([
  "sap/ui/core/mvc/Controller",
  "sap/m/MessageToast",
  "sap/m/MessageBox"
], function (Controller, MessageToast, MessageBox) {{
  "use strict";

  return Controller.extend("{namespace}.controller.RequestEntry", {{
    onInit: function () {{
      this.getOwnerComponent().getRouter().getRoute("requestEntry").attachPatternMatched(this._onPatternMatched, this);
    }},

    _onPatternMatched: function (oEvent) {{
      var sPONumber = oEvent.getParameter("arguments").poNumber || "4500019280";
      var oModel = this.getView().getModel();
      var aOrders = oModel.getProperty("/purchaseOrders") || [];
      var oPO = aOrders.find(function (item) {{ return item.poNumber === sPONumber; }}) || aOrders[0];
      
      if (oPO) {{
        oModel.setProperty("/activeRequest", {{
          poNumber: oPO.poNumber,
          supplierName: oPO.supplierName,
          supplierCode: oPO.supplierCode,
          plant: oPO.plant,
          purchasingOrg: "1000",
          companyCode: "1000",
          openValue: oPO.openValue,
          currency: oPO.currency,
          vehicleNumber: "MH-12-AB-1234",
          driverName: "Ramesh Kumar",
          driverMobile: "9876543210",
          deliveryNote: "DN-2026-9901",
          requestedEntryDate: new Date().toISOString().split("T")[0],
          timeSlot: "SLOT-01",
          gateBay: "GATE-01",
          additionalPersons: 0,
          purpose: "Material delivery against scheduled PO lines",
          remarks: "Driver carrying valid ID, PPE, and delivery challan copy.",
          items: [
            {{ itemNumber: "00010", materialCode: "MAT-ENG-4401", materialName: "Heavy Bearing Assembly", poQty: "100", deliveryQty: "100", unit: "EA" }},
            {{ itemNumber: "00020", materialCode: "MAT-ENG-4402", materialName: "Hydraulic Seal Ring", poQty: "50", deliveryQty: "50", unit: "EA" }}
          ]
        }});
      }}
    }},

    onSubmitRequest: function () {{
      var oModel = this.getView().getModel();
      var oReq = oModel.getProperty("/activeRequest");
      
      // Business Rule Validation (Rule BR-01 & BR-02)
      if (!oReq.vehicleNumber || oReq.vehicleNumber.trim().length < 5) {{
        MessageBox.error("Please enter a valid vehicle registration number.");
        return;
      }}
      if (!oReq.driverName || oReq.driverName.trim().length < 2) {{
        MessageBox.error("Please enter driver full name.");
        return;
      }}
      if (!oReq.driverMobile || oReq.driverMobile.length < 10) {{
        MessageBox.error("Please enter a valid 10-digit mobile number for SMS dispatch.");
        return;
      }}

      var that = this;
      MessageBox.confirm("Submit gate pass request for PO " + oReq.poNumber + " for Level 1 Operational Approval?", {{
        title: "Confirm Gate Pass Submission",
        onClose: function (sAction) {{
          if (sAction === MessageBox.Action.OK) {{
            MessageToast.show("Gate Pass Request GP-2026-0042 submitted successfully. Routed to Level 1 Approver Inbox.");
            that.getOwnerComponent().getRouter().navTo("approvalInbox");
          }}
        }}
      }});
    }},

    onSaveDraft: function () {{
      MessageToast.show("Gate pass draft saved. You can resume editing anytime.");
    }},

    onNavBack: function () {{
      this.getOwnerComponent().getRouter().navTo("listReport");
    }}
  }});
}});
'''

    # 7. Approval Inbox View (SCR-04 & SCR-05: My Inbox L1 & L2 Operational Review)
    approval_inbox_view = f'''<mvc:View
  controllerName="{namespace}.controller.ApprovalInbox"
  xmlns:mvc="sap.ui.core.mvc"
  xmlns="sap.m"
  xmlns:core="sap.ui.core"
  xmlns:form="sap.ui.layout.form">
  <SplitContainer id="splitApp" initialMaster="masterPage" initialDetail="detailPage">
    <masterPages>
      <Page id="masterPage" title="Approval Worklist (My Inbox)">
        <subHeader>
          <OverflowToolbar>
            <SearchField width="100%" placeholder="Search requests..." liveChange=".onSearchTasks"/>
          </OverflowToolbar>
        </subHeader>
        <content>
          <List id="tasksList" items="{{/approvalTasks}}" mode="SingleSelectMaster" selectionChange=".onTaskSelect">
            <items>
              <ObjectListItem
                title="{{requestNumber}} — {{supplierName}}"
                type="Active"
                number="{{openValue}}"
                numberUnit="{{currency}}">
                <firstStatus>
                  <ObjectStatus text="{{priority}}" state="{{priorityState}}"/>
                </firstStatus>
                <attributes>
                  <ObjectAttribute text="PO: {{poNumber}} · Plant: {{plant}}"/>
                  <ObjectAttribute text="Entry: {{requestedDate}} ({{timeSlot}})"/>
                </attributes>
              </ObjectListItem>
            </items>
          </List>
        </content>
      </Page>
    </masterPages>
    <detailPages>
      <Page id="detailPage" title="Operational Review — {{/selectedTask/requestNumber}}">
        <headerContent>
          <ObjectStatus text="{{/selectedTask/approvalStage}}" state="Warning"/>
        </headerContent>
        <content>
          <VBox class="sapUiSmallMargin">
            <Panel headerText="1. Request Context &amp; PO Reference" expandable="false">
              <form:SimpleForm layout="ResponsiveGridLayout" labelSpanXL="4" labelSpanL="4" labelSpanM="4" columnsXL="2" columnsL="2">
                <Label text="Request Number"/><Text text="{{/selectedTask/requestNumber}}"/>
                <Label text="Purchase Order"/><Text text="{{/selectedTask/poNumber}} (Value: {{/selectedTask/openValue}} {{/selectedTask/currency}})"/>
                <Label text="Supplier Name"/><Text text="{{/selectedTask/supplierName}}"/>
                <Label text="Receiving Plant"/><Text text="{{/selectedTask/plant}} - Chakan Logistics Bay"/>
              </form:SimpleForm>
            </Panel>

            <Panel headerText="2. Transporter &amp; Entry Schedule" expandable="false" class="sapUiSmallMarginTop">
              <form:SimpleForm layout="ResponsiveGridLayout" labelSpanXL="4" labelSpanL="4" labelSpanM="4" columnsXL="2" columnsL="2">
                <Label text="Vehicle Number"/><Text text="{{/selectedTask/vehicleNumber}}"/>
                <Label text="Driver Name"/><Text text="{{/selectedTask/driverName}} (Mobile: {{/selectedTask/driverMobile}})"/>
                <Label text="Delivery Note"/><Text text="{{/selectedTask/deliveryNote}}"/>
                <Label text="Requested Schedule"/><Text text="{{/selectedTask/requestedDate}} · {{/selectedTask/timeSlot}}"/>
              </form:SimpleForm>
            </Panel>

            <Panel headerText="3. Approver Decision &amp; Verification Checks" expandable="false" class="sapUiSmallMarginTop">
              <VBox>
                <CheckBox text="Purchase Order is valid, released, and unfulfilled line balances match delivery note." selected="true"/>
                <CheckBox text="Driver identification and vehicle registration verified against transporter manifest." selected="true"/>
                <CheckBox text="Plant delivery capacity and dock bay schedule confirmed." selected="true"/>
                <Label text="Decision Reason / Return Comments" class="sapUiSmallMarginTop"/>
                <TextArea id="decisionComment" value="{{/selectedTask/decisionComment}}" width="100%" rows="3" placeholder="Enter reason notes for approval, return, or rejection..."/>
              </VBox>
            </Panel>
          </VBox>
        </content>
        <footer>
          <OverflowToolbar>
            <ToolbarSpacer/>
            <Button text="Approve Request" type="Accept" icon="sap-icon://accept" press=".onApprovePress"/>
            <Button text="Return to Supplier" type="Attention" icon="sap-icon://undo" press=".onReturnPress"/>
            <Button text="Reject Request" type="Reject" icon="sap-icon://decline" press=".onRejectPress"/>
          </OverflowToolbar>
        </footer>
      </Page>
    </detailPages>
  </SplitContainer>
</mvc:View>
'''

    approval_inbox_controller = f'''sap.ui.define([
  "sap/ui/core/mvc/Controller",
  "sap/m/MessageToast",
  "sap/m/MessageBox"
], function (Controller, MessageToast, MessageBox) {{
  "use strict";

  return Controller.extend("{namespace}.controller.ApprovalInbox", {{
    onInit: function () {{
      var oModel = this.getView().getModel();
      var aTasks = oModel.getProperty("/approvalTasks") || [];
      if (aTasks.length > 0) {{
        oModel.setProperty("/selectedTask", Object.assign({{}}, aTasks[0]));
      }}
    }},

    onTaskSelect: function (oEvent) {{
      var oItem = oEvent.getParameter("listItem");
      var oTask = oItem.getBindingContext().getObject();
      this.getView().getModel().setProperty("/selectedTask", Object.assign({{}}, oTask));
    }},

    onApprovePress: function () {{
      var oTask = this.getView().getModel().getProperty("/selectedTask");
      var that = this;
      MessageBox.confirm("Approve gate pass request " + oTask.requestNumber + "? An immutable cryptographic QR code pass will be generated.", {{
        title: "Approve Gate Pass",
        onClose: function (sAction) {{
          if (sAction === MessageBox.Action.OK) {{
            MessageToast.show("Request " + oTask.requestNumber + " approved. Pass generated.");
            that.getOwnerComponent().getRouter().navTo("passDownload", {{ passId: oTask.requestNumber }});
          }}
        }}
      }});
    }},

    onReturnPress: function () {{
      var oTask = this.getView().getModel().getProperty("/selectedTask");
      var sComment = this.byId("decisionComment").getValue();
      if (!sComment) {{
        MessageBox.error("Please enter return reason comments explaining what the supplier must correct.");
        return;
      }}
      MessageToast.show("Request " + oTask.requestNumber + " returned to supplier for correction.");
    }},

    onRejectPress: function () {{
      var oTask = this.getView().getModel().getProperty("/selectedTask");
      var sComment = this.byId("decisionComment").getValue();
      if (!sComment) {{
        MessageBox.error("Please enter a formal rejection reason.");
        return;
      }}
      MessageBox.warning("Confirm rejection of request " + oTask.requestNumber + "? This cannot be undone.", {{
        title: "Reject Gate Pass Request",
        actions: [MessageBox.Action.OK, MessageBox.Action.CANCEL],
        onClose: function (sAction) {{
          if (sAction === MessageBox.Action.OK) {{
            MessageToast.show("Request " + oTask.requestNumber + " has been rejected.");
          }}
        }}
      }});
    }}
  }});
}});
'''

    # 8. Gate Verification Scanner View (SCR-07: Handheld QR Code Scanner)
    gate_verification_view = f'''<mvc:View
  controllerName="{namespace}.controller.GateVerification"
  xmlns:mvc="sap.ui.core.mvc"
  xmlns="sap.m"
  xmlns:core="sap.ui.core"
  xmlns:layout="sap.ui.layout">
  <Page title="Gate Security Verification (SCR-07)" showNavButton="false" class="sapUiContentPadding">
    <headerContent>
      <ObjectStatus text="Gate 1 Scanner Active" state="Success" icon="sap-icon://connected"/>
    </headerContent>
    <content>
      <VBox class="scannerContainer">
        <!-- Live Viewfinder Box -->
        <Panel class="qrViewfinderPanel" expandable="false">
          <VBox alignItems="Center" class="qrViewfinderBox">
            <div class="laserLine"/>
            <Avatar src="sap-icon://qr-code" displaySize="XL" class="sapUiMediumMarginTop"/>
            <Title text="ALIGN QR CODE WITHIN FRAME" level="H3" class="sapUiSmallMarginTop"/>
            <Text text="Hold mobile camera 15-20 cm from supplier PDF gate pass or screen"/>
            <HBox class="sapUiSmallMarginTop" width="100%" justifyContent="Center">
              <Input id="tokenInput" width="280px" placeholder="Or enter 16-char token code..." value="{{/scanState/inputToken}}"/>
              <Button text="Verify" type="Emphasized" icon="sap-icon://search" press=".onVerifyTokenPress" class="sapUiTinyMarginBegin"/>
            </HBox>
          </VBox>
        </Panel>

        <!-- Verification Result Card (Minimum Disclosure) -->
        <Panel headerText="Security Verification Result" class="sapUiSmallMarginTop" expandable="false">
          <MessageStrip
            text="✓ GATE PASS VERIFIED — ENTRY AUTHORIZED (Valid Cryptographic Signature)"
            type="Success"
            showIcon="true"
            class="sapUiSmallMarginBottom"/>
          
          <VBox class="verifiedPassCard">
            <HBox justifyContent="SpaceBetween" alignItems="Center">
              <Title text="Pass: {{/scanState/passNumber}}" level="H2"/>
              <ObjectStatus text="ACTIVE VALID" state="Success"/>
            </HBox>
            <layout:HorizontalLayout allowWrapping="true" class="sapUiSmallMarginTop">
              <layout:VerticalLayout class="sapUiLargeMarginEnd">
                <ObjectStatus title="Supplier" text="{{/scanState/supplierName}}"/>
                <ObjectStatus title="Masked Vehicle" text="{{/scanState/maskedVehicle}}"/>
                <ObjectStatus title="Masked Driver" text="{{/scanState/maskedDriver}}"/>
              </layout:VerticalLayout>
              <layout:VerticalLayout class="sapUiLargeMarginEnd">
                <ObjectStatus title="Designated Gate" text="{{/scanState/gateBay}}"/>
                <ObjectStatus title="Validity Window" text="{{/scanState/validityWindow}}"/>
                <ObjectStatus title="Delivery Note" text="{{/scanState/deliveryNote}}"/>
              </layout:VerticalLayout>
              <layout:VerticalLayout>
                <ObjectStatus title="Safety Requirements" text="Helmet + Safety Shoes + Hi-Vis Vest" state="Warning"/>
                <ObjectStatus title="Authorized Items" text="{{/scanState/itemSummary}}"/>
              </layout:VerticalLayout>
            </layout:HorizontalLayout>

            <!-- Touch Decision Actions for Gate Guard -->
            <HBox class="sapUiMediumMarginTop" justifyContent="Center">
              <Button text="ADMIT VEHICLE" type="Accept" icon="sap-icon://accept" press=".onAdmitVehicle" class="admitBtn sapUiMediumMarginEnd"/>
              <Button text="DENY ENTRY" type="Reject" icon="sap-icon://decline" press=".onDenyEntry" class="denyBtn"/>
            </HBox>
          </VBox>
        </Panel>
      </VBox>
    </content>
  </Page>
</mvc:View>
'''

    gate_verification_controller = f'''sap.ui.define([
  "sap/ui/core/mvc/Controller",
  "sap/m/MessageToast",
  "sap/m/MessageBox"
], function (Controller, MessageToast, MessageBox) {{
  "use strict";

  return Controller.extend("{namespace}.controller.GateVerification", {{
    onInit: function () {{
      var oModel = this.getView().getModel();
      oModel.setProperty("/scanState", {{
        inputToken: "GP-TOKEN-9921-X",
        passNumber: "GP-2026-0041",
        supplierName: "Apex Engineering Solutions Pvt Ltd",
        maskedVehicle: "MH-12-AB-****",
        maskedDriver: "R*** K****",
        gateBay: "Gate 1 - North Logistics Inward",
        validityWindow: "Today 08:00 - 18:00 (Active)",
        deliveryNote: "DN-2026-9901",
        itemSummary: "Heavy Bearing Assemblies (100 EA)"
      }});
    }},

    onVerifyTokenPress: function () {{
      var sToken = this.byId("tokenInput").getValue();
      if (!sToken) {{
        MessageToast.show("Please enter or scan a pass token.");
        return;
      }}
      MessageToast.show("QR Token " + sToken + " cryptographic hash validated against SAP S/4HANA.");
    }},

    onAdmitVehicle: function () {{
      var oScan = this.getView().getModel().getProperty("/scanState");
      MessageBox.confirm("Record entry event and admit vehicle " + oScan.maskedVehicle + " through Gate 1?", {{
        title: "Confirm Gate Admission",
        onClose: function (sAction) {{
          if (sAction === MessageBox.Action.OK) {{
            MessageToast.show("Entry timestamp recorded in SAP. Gate barrier raised.");
          }}
        }}
      }});
    }},

    onDenyEntry: function () {{
      var that = this;
      MessageBox.error("Specify reason for entry denial (e.g. invalid PPE, expired validity, mismatched plates):", {{
        title: "Deny Gate Entry",
        actions: [MessageBox.Action.OK, MessageBox.Action.CANCEL],
        onClose: function (sAction) {{
          if (sAction === MessageBox.Action.OK) {{
            MessageToast.show("Denial event recorded and alert sent to Security In-charge.");
          }}
        }}
      }});
    }}
  }});
}});
'''

    # 9. Pass Download View (SCR-06: Approved Gate Pass PDF & QR Preview)
    pass_download_view = f'''<mvc:View
  controllerName="{namespace}.controller.PassDownload"
  xmlns:mvc="sap.ui.core.mvc"
  xmlns="sap.m"
  xmlns:layout="sap.ui.layout">
  <Page title="Approved Gate Pass (SCR-06)" showNavButton="true" navButtonPress=".onNavBack" class="sapUiContentPadding">
    <content>
      <VBox alignItems="Center" class="passDownloadCard sapUiMediumMargin">
        <Panel width="600px" class="pdfPassPreview">
          <VBox alignItems="Center">
            <Avatar src="sap-icon://pdf-attachment" displaySize="L" class="sapUiSmallMarginBottom"/>
            <Title text="GATE ENTRY PASS — {{/activePass/passNumber}}" level="H2"/>
            <Text text="Issued for PO {{/activePass/poNumber}} · Plant {{/activePass/plant}}"/>
            
            <HBox class="sapUiMediumMarginTop" justifyContent="Center" alignItems="Center">
              <Avatar src="sap-icon://qr-code" displaySize="XL" class="qrPassImage sapUiMediumMarginEnd"/>
              <VBox>
                <ObjectStatus title="Pass Status" text="ISSUED &amp; ACTIVE" state="Success"/>
                <ObjectStatus title="Supplier" text="{{/activePass/supplierName}}"/>
                <ObjectStatus title="Vehicle No" text="{{/activePass/vehicleNumber}}"/>
                <ObjectStatus title="Driver" text="{{/activePass/driverName}}"/>
                <ObjectStatus title="Validity Window" text="{{/activePass/validity}}"/>
              </VBox>
            </HBox>

            <Button text="Download Official PDF Gate Pass" type="Emphasized" icon="sap-icon://download" press=".onDownloadPDF" class="sapUiMediumMarginTop"/>
          </VBox>
        </Panel>
      </VBox>
    </content>
  </Page>
</mvc:View>
'''

    pass_download_controller = f'''sap.ui.define([
  "sap/ui/core/mvc/Controller",
  "sap/m/MessageToast"
], function (Controller, MessageToast) {{
  "use strict";

  return Controller.extend("{namespace}.controller.PassDownload", {{
    onInit: function () {{
      var oModel = this.getView().getModel();
      oModel.setProperty("/activePass", {{
        passNumber: "GP-2026-0041",
        poNumber: "4500019280",
        plant: "1000 - Chakan Logistics",
        supplierName: "Apex Engineering Solutions Pvt Ltd",
        vehicleNumber: "MH-12-AB-1234",
        driverName: "Ramesh Kumar",
        validity: "2026-09-04 08:00 to 18:00"
      }});
    }},

    onDownloadPDF: function () {{
      MessageToast.show("Generating and downloading official PDF Gate Pass with QR code...");
    }},

    onNavBack: function () {{
      this.getOwnerComponent().getRouter().navTo("listReport");
    }}
  }});
}});
'''

    # 10. Mock Data JSON
    mock_data = {
        "project": {
            "id": project.id,
            "name": display_name,
            "generatedAt": generated_at,
        },
        "purchaseOrders": [
            {
                "poNumber": "4500019280",
                "supplierCode": "100482",
                "supplierName": "Apex Engineering Solutions Pvt Ltd",
                "deliveryDate": "2026-09-04",
                "plant": "1000",
                "itemCount": 2,
                "openValue": "145,000.00",
                "currency": "INR",
                "status": "Eligible",
                "statusState": "Success",
            },
            {
                "poNumber": "4500019281",
                "supplierCode": "100482",
                "supplierName": "Apex Engineering Solutions Pvt Ltd",
                "deliveryDate": "2026-09-06",
                "plant": "1010",
                "itemCount": 5,
                "openValue": "320,500.00",
                "currency": "INR",
                "status": "Eligible",
                "statusState": "Success",
            },
            {
                "poNumber": "4500019282",
                "supplierCode": "100512",
                "supplierName": "Bharat Precision Forgings Ltd",
                "deliveryDate": "2026-09-02",
                "plant": "1000",
                "itemCount": 1,
                "openValue": "88,000.00",
                "currency": "INR",
                "status": "Pass Requested",
                "statusState": "Warning",
            },
        ],
        "approvalTasks": [
            {
                "requestNumber": "GP-2026-0041",
                "poNumber": "4500019280",
                "supplierName": "Apex Engineering Solutions Pvt Ltd",
                "plant": "1000",
                "vehicleNumber": "MH-12-AB-1234",
                "driverName": "Ramesh Kumar",
                "driverMobile": "9876543210",
                "deliveryNote": "DN-2026-9901",
                "requestedDate": "2026-09-04",
                "timeSlot": "08:00 - 12:00",
                "openValue": "145,000.00",
                "currency": "INR",
                "priority": "High",
                "priorityState": "Error",
                "approvalStage": "Level 1 Operational Review",
                "decisionComment": "",
            },
            {
                "requestNumber": "GP-2026-0040",
                "poNumber": "4500019275",
                "supplierName": "Vortex Fasteners & Seals",
                "plant": "1010",
                "vehicleNumber": "MH-14-CD-5678",
                "driverName": "Sunil Patil",
                "driverMobile": "9822012345",
                "deliveryNote": "DN-2026-8840",
                "requestedDate": "2026-09-04",
                "timeSlot": "12:00 - 16:00",
                "openValue": "54,200.00",
                "currency": "INR",
                "priority": "Medium",
                "priorityState": "Warning",
                "approvalStage": "Level 2 Final Authorization",
                "decisionComment": "",
            },
        ],
        "requirements": requirements,
    }

    # 11. i18n properties
    i18n_properties = f'''appTitle={display_name}
appDescription=SAP Fiori End-to-End Application Grounded in BRD & FSD
listTitle=Purchase Orders
createRequest=Create Gate Pass
export=Export to Excel
refresh=Refresh
search=Search
poNumber=PO Number
supplier=Supplier
deliveryDate=Delivery Date
plant=Plant
status=Status
validateSubmit=Validate & Submit
saveDraft=Save Draft
approve=Approve
return=Return to Supplier
reject=Reject
admit=Admit Vehicle
deny=Deny Entry
'''

    # 12. CSS Styles
    css_style = f'''.sapUiBody {{
  background: var(--sapBackgroundColor, #f5f6f7);
}}

.scannerContainer {{
  max-width: 720px;
  margin: 0 auto;
}}

.qrViewfinderBox {{
  padding: 30px;
  border: 2px dashed var(--sapBrandColor, #0d6b50);
  border-radius: 16px;
  background: #f0f7f4;
  position: relative;
  overflow: hidden;
}}

.laserLine {{
  width: 100%;
  height: 3px;
  background: #ef7c45;
  box-shadow: 0 0 10px #ef7c45;
  position: absolute;
  top: 30%;
  animation: laserSweep 2s infinite ease-in-out;
}}

@keyframes laserSweep {{
  0% {{ top: 15%; opacity: 0.2; }}
  50% {{ top: 85%; opacity: 1; }}
  100% {{ top: 15%; opacity: 0.2; }}
}}

.verifiedPassCard {{
  padding: 16px;
  background: #ffffff;
  border: 1px solid #d9ddd7;
  border-radius: 12px;
}}

.admitBtn {{
  min-width: 160px;
  font-weight: bold;
}}

.denyBtn {{
  min-width: 140px;
}}
'''

    # 13. Component.js
    component_js = f'''sap.ui.define([
  "sap/ui/core/UIComponent",
  "sap/ui/model/json/JSONModel"
], function (UIComponent, JSONModel) {{
  "use strict";

  return UIComponent.extend("{namespace}.Component", {{
    metadata: {{
      manifest: "json"
    }},

    init: function () {{
      UIComponent.prototype.init.apply(this, arguments);
      this.getRouter().initialize();
    }}
  }});
}});
'''

    # 14. HTML Bootstrap
    index_html = f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{display_name}</title>
  <script
    id="sap-ui-bootstrap"
    src="resources/sap-ui-core.js"
    data-sap-ui-theme="sap_horizon"
    data-sap-ui-compat-version="edge"
    data-sap-ui-async="true"
    data-sap-ui-on-init="module:sap/ui/core/ComponentSupport"
    data-sap-ui-resource-roots='{{"{namespace}": "./"}}'>
  </script>
</head>
<body class="sapUiBody sapUiSizeCompact" id="content">
  <div data-sap-ui-component data-name="{namespace}" data-id="container" data-settings='{{"id":"{namespace}"}}'></div>
</body>
</html>
'''

    # -------------------------------------------------------------
    # ABAP Cloud & RAP Backend Files
    # -------------------------------------------------------------

    # A) Root CDS View Entity
    cds_root_source = f'''@AccessControl.authorizationCheck: #CHECK
@EndUserText.label: '{display_name} - Root Entity'
define root view entity {cds_root}
  as select from zt{slug[:8].replace("-", "_")}_head as Header
  composition [0..*] of {cds_item} as _Items
{{
  key Header.pass_uuid          as PassUUID,
      Header.request_number     as RequestNumber,
      Header.po_number          as PONumber,
      Header.supplier_code      as SupplierCode,
      Header.supplier_name      as SupplierName,
      Header.plant              as Plant,
      Header.company_code       as CompanyCode,
      Header.vehicle_number     as VehicleNumber,
      Header.driver_name        as DriverName,
      Header.driver_mobile      as DriverMobile,
      Header.delivery_note      as DeliveryNote,
      Header.requested_date     as RequestedEntryDate,
      Header.time_slot          as TimeSlot,
      Header.gate_bay           as GateBay,
      Header.status             as Status,
      Header.qr_token           as QRToken,
      Header.created_by         as CreatedBy,
      Header.created_at         as CreatedAt,
      Header.last_changed_by    as LastChangedBy,
      Header.last_changed_at    as LastChangedAt,

      _Items
}}
'''

    # B) Item CDS View Entity
    cds_item_source = f'''@AccessControl.authorizationCheck: #CHECK
@EndUserText.label: '{display_name} - Item Entity'
define view entity {cds_item}
  as select from zt{slug[:8].replace("-", "_")}_item as Item
  association to parent {cds_root} as _Header
    on $projection.PassUUID = _Header.PassUUID
{{
  key Item.item_uuid     as ItemUUID,
      Item.pass_uuid     as PassUUID,
      Item.item_number   as ItemNumber,
      Item.material_code as MaterialCode,
      Item.material_name as MaterialName,
      @Semantics.quantity.unitOfMeasure: 'Unit'
      Item.quantity      as Quantity,
      Item.unit          as Unit,

      _Header
}}
'''

    # C) Consumption Projection View
    cds_proj_source = f'''@EndUserText.label: '{display_name} - Projection View'
@AccessControl.authorizationCheck: #CHECK
@Metadata.allowExtensions: true
@Search.searchable: true
define root view entity {cds_proj}
  provider contract transactional_query
  as projection on {cds_root}
{{
  key PassUUID,
      @Search.defaultSearchElement: true
      RequestNumber,
      @Search.defaultSearchElement: true
      PONumber,
      SupplierCode,
      SupplierName,
      Plant,
      VehicleNumber,
      DriverName,
      DriverMobile,
      DeliveryNote,
      RequestedEntryDate,
      TimeSlot,
      GateBay,
      Status,
      QRToken,
      CreatedAt,
      
      _Items : redirected to composition child {cds_item_proj}
}}
'''

    cds_item_proj_source = f'''@EndUserText.label: '{display_name} - Item Projection'
@AccessControl.authorizationCheck: #CHECK
define view entity {cds_item_proj}
  as projection on {cds_item}
{{
  key ItemUUID,
      PassUUID,
      ItemNumber,
      MaterialCode,
      MaterialName,
      Quantity,
      Unit,
      
      _Header : redirected to parent {cds_proj}
}}
'''

    # D) Metadata Extension (Annotations for Fiori Elements)
    mde_source = f'''@Metadata.layer: #CUSTOMER
@UI: {{
  headerInfo: {{
    typeName: '{display_name}',
    typeNamePlural: '{display_name} Requests',
    title: {{ type: #STANDARD, value: 'RequestNumber' }},
    description: {{ value: 'SupplierName' }}
  }}
}}
annotate view {cds_proj} with
{{
  @UI.facet: [
    {{ id: 'HeaderFacet', purpose: #HEADER, type: #FIELDGROUP_REFERENCE, targetQualifier: 'HeaderData', position: 10 }},
    {{ id: 'GeneralSection', purpose: #STANDARD, type: #IDENTIFICATION_REFERENCE, label: 'General Information', position: 10 }},
    {{ id: 'VehicleSection', purpose: #STANDARD, type: #FIELDGROUP_REFERENCE, targetQualifier: 'VehicleData', label: 'Transporter Details', position: 20 }},
    {{ id: 'ItemsSection', purpose: #STANDARD, type: #LINEITEM_REFERENCE, targetElement: '_Items', label: 'Authorized Line Items', position: 30 }}
  ]

  @UI.lineItem: [ {{ position: 10, label: 'Request No' }},
                  {{ type: #FOR_ACTION, dataAction: 'approveRequest', label: 'Approve' }},
                  {{ type: #FOR_ACTION, dataAction: 'rejectRequest', label: 'Reject' }} ]
  @UI.selectionField: [ {{ position: 10 }} ]
  RequestNumber;

  @UI.lineItem: [ {{ position: 20, label: 'PO Number' }} ]
  @UI.selectionField: [ {{ position: 20 }} ]
  PONumber;

  @UI.lineItem: [ {{ position: 30, label: 'Supplier' }} ]
  SupplierName;

  @UI.lineItem: [ {{ position: 40, label: 'Vehicle Number' }} ]
  @UI.fieldGroup: [ {{ qualifier: 'VehicleData', position: 10, label: 'Vehicle Registration' }} ]
  VehicleNumber;

  @UI.lineItem: [ {{ position: 50, label: 'Driver Name' }} ]
  @UI.fieldGroup: [ {{ qualifier: 'VehicleData', position: 20, label: 'Driver Full Name' }} ]
  DriverName;

  @UI.lineItem: [ {{ position: 60, label: 'Entry Date' }} ]
  RequestedEntryDate;

  @UI.lineItem: [ {{ position: 70, label: 'Status' }} ]
  Status;
}}
'''

    # E) Managed RAP Behavior Definition
    bdef_source = f'''managed implementation in class {behavior_class.lower()} unique;
strict ( 2 );
with draft;

define behavior for {cds_root} alias PassRequest
persistent table zt{slug[:8].replace("-", "_")}_head
draft table zt{slug[:8].replace("-", "_")}_d_hd
lock master total etag LastChangedAt
authorization master ( instance )
etag master LastChangedAt
{{
  create;
  update;
  delete;

  association _Items {{ create; with draft; }}

  field ( numbering : managed, readonly ) PassUUID;
  field ( readonly ) RequestNumber, Status, QRToken, CreatedBy, CreatedAt, LastChangedBy, LastChangedAt;
  field ( mandatory ) PONumber, VehicleNumber, DriverName, DriverMobile, RequestedEntryDate;

  action ( features : instance ) approveRequest result [1] $self;
  action ( features : instance ) rejectRequest parameter ZA_{suffix[:10]}_Reason result [1] $self;
  action ( features : instance ) returnToSupplier parameter ZA_{suffix[:10]}_Reason result [1] $self;
  action ( features : instance ) admitVehicle result [1] $self;
  action ( features : instance ) denyEntry parameter ZA_{suffix[:10]}_Reason result [1] $self;

  determination setInitialStatus on modify {{ create; }}
  determination generatePassNumber on save {{ create; }}
  determination createQRToken on modify {{ field Status; }}

  validation validateDeliveryDate on save {{ create; field RequestedEntryDate; }}
  validation validateTransporter on save {{ create; update; field VehicleNumber, DriverMobile; }}

  draft action Edit;
  draft action Activate;
  draft action Discard;
  draft action Resume;
  draft determine action Prepare {{
    validation validateDeliveryDate;
    validation validateTransporter;
  }}
}}

define behavior for {cds_item} alias PassItem
persistent table zt{slug[:8].replace("-", "_")}_item
draft table zt{slug[:8].replace("-", "_")}_d_it
lock dependent by _Header
authorization dependent by _Header
etag master ItemUUID
{{
  update;
  delete;

  field ( numbering : managed, readonly ) ItemUUID;
  field ( readonly ) PassUUID;
  association _Header {{ with draft; }}
}}
'''

    # F) Behavior Pool Class Implementation
    behavior_class_source = f'''CLASS {behavior_class} DEFINITION PUBLIC ABSTRACT FINAL FOR BEHAVIOR OF {cds_root}.
ENDCLASS.

CLASS {behavior_class} IMPLEMENTATION.
ENDCLASS.
'''

    behavior_class_local_source = f'''CLASS lhc_PassRequest DEFINITION INHERITING FROM cl_abap_behavior_handler.
  PRIVATE SECTION.
    METHODS get_instance_authorizations FOR INSTANCE AUTHORIZATION
      IMPORTING keys REQUEST requested_authorizations FOR PassRequest RESULT result.

    METHODS get_instance_features FOR INSTANCE FEATURES
      IMPORTING keys REQUEST requested_features FOR PassRequest RESULT result.

    METHODS approveRequest FOR MODIFY
      IMPORTING keys FOR ACTION PassRequest~approveRequest RESULT result.

    METHODS rejectRequest FOR MODIFY
      IMPORTING keys FOR ACTION PassRequest~rejectRequest RESULT result.

    METHODS returnToSupplier FOR MODIFY
      IMPORTING keys FOR ACTION PassRequest~returnToSupplier RESULT result.

    METHODS admitVehicle FOR MODIFY
      IMPORTING keys FOR ACTION PassRequest~admitVehicle RESULT result.

    METHODS setInitialStatus FOR DETERMINE ON MODIFY
      IMPORTING keys FOR PassRequest~setInitialStatus.

    METHODS generatePassNumber FOR DETERMINE ON SAVE
      IMPORTING keys FOR PassRequest~generatePassNumber.

    METHODS validateDeliveryDate FOR VALIDATE ON SAVE
      IMPORTING keys FOR PassRequest~validateDeliveryDate.

    METHODS validateTransporter FOR VALIDATE ON SAVE
      IMPORTING keys FOR PassRequest~validateTransporter.
ENDCLASS.

CLASS lhc_PassRequest IMPLEMENTATION.
  METHOD get_instance_authorizations.
    " Authorization check against {auth_class}
    LOOP AT keys INTO DATA(key).
      APPEND VALUE #( %tky = key-%tky %action-approveRequest = if_abap_behv=>auth-allowed ) TO result.
    ENDLOOP.
  ENDMETHOD.

  METHOD get_instance_features.
    READ ENTITIES OF {cds_root} IN LOCAL MODE
      ENTITY PassRequest
      FIELDS ( Status ) WITH CORRESPONDING #( keys )
      RESULT DATA(requests).

    LOOP AT requests INTO DATA(req).
      DATA(is_submitted) = COND #( WHEN req-Status = 'Submitted' THEN if_abap_behv=>fc-o-enabled ELSE if_abap_behv=>fc-o-disabled ).
      APPEND VALUE #( %tky = req-%tky
                      %action-approveRequest = is_submitted
                      %action-rejectRequest  = is_submitted ) TO result.
    ENDLOOP.
  ENDMETHOD.

  METHOD approveRequest.
    MODIFY ENTITIES OF {cds_root} IN LOCAL MODE
      ENTITY PassRequest
      UPDATE FIELDS ( Status QRToken )
      WITH VALUE #( FOR key IN keys (
        %tky    = key-%tky
        Status  = 'Approved'
        QRToken = |GP-TOKEN-{{ cl_system_uuid=>create_uuid_c22_static( ) }}|
      ) ).

    READ ENTITIES OF {cds_root} IN LOCAL MODE
      ENTITY PassRequest
      ALL FIELDS WITH CORRESPONDING #( keys )
      RESULT DATA(updated_records).

    result = VALUE #( FOR rec IN updated_records ( %tky = rec-%tky %param = rec ) ).
  ENDMETHOD.

  METHOD rejectRequest.
    MODIFY ENTITIES OF {cds_root} IN LOCAL MODE
      ENTITY PassRequest
      UPDATE FIELDS ( Status )
      WITH VALUE #( FOR key IN keys (
        %tky   = key-%tky
        Status = 'Rejected'
      ) ).
  ENDMETHOD.

  METHOD returnToSupplier.
    MODIFY ENTITIES OF {cds_root} IN LOCAL MODE
      ENTITY PassRequest
      UPDATE FIELDS ( Status )
      WITH VALUE #( FOR key IN keys (
        %tky   = key-%tky
        Status = 'Returned'
      ) ).
  ENDMETHOD.

  METHOD admitVehicle.
    MODIFY ENTITIES OF {cds_root} IN LOCAL MODE
      ENTITY PassRequest
      UPDATE FIELDS ( Status )
      WITH VALUE #( FOR key IN keys (
        %tky   = key-%tky
        Status = 'Admitted'
      ) ).
  ENDMETHOD.

  METHOD setInitialStatus.
    MODIFY ENTITIES OF {cds_root} IN LOCAL MODE
      ENTITY PassRequest
      UPDATE FIELDS ( Status )
      WITH VALUE #( FOR key IN keys ( %tky = key-%tky Status = 'Draft' ) ).
  ENDMETHOD.

  METHOD generatePassNumber.
    " Number range determination
  ENDMETHOD.

  METHOD validateDeliveryDate.
    READ ENTITIES OF {cds_root} IN LOCAL MODE
      ENTITY PassRequest
      FIELDS ( RequestedEntryDate ) WITH CORRESPONDING #( keys )
      RESULT DATA(requests).

    LOOP AT requests INTO DATA(req).
      IF req-RequestedEntryDate < cl_abap_context_info=>get_system_date( ).
        APPEND VALUE #( %tky = req-%tky ) TO failed-passrequest.
        APPEND VALUE #( %tky = req-%tky
                        %msg = new_message_with_text(
                          severity = if_abap_behv_message=>severity-error
                          text     = 'Requested entry date cannot be in the past' ) ) TO reported-passrequest.
      ENDIF;
    ENDLOOP.
  ENDMETHOD.

  METHOD validateTransporter.
    READ ENTITIES OF {cds_root} IN LOCAL MODE
      ENTITY PassRequest
      FIELDS ( VehicleNumber DriverMobile ) WITH CORRESPONDING #( keys )
      RESULT DATA(requests).

    LOOP AT requests INTO DATA(req).
      IF req-VehicleNumber IS INITIAL OR req-DriverMobile IS INITIAL.
        APPEND VALUE #( %tky = req-%tky ) TO failed-passrequest.
        APPEND VALUE #( %tky = req-%tky
                        %msg = new_message_with_text(
                          severity = if_abap_behv_message=>severity-error
                          text     = 'Vehicle registration number and Driver mobile number are mandatory' ) ) TO reported-passrequest.
      ENDIF;
    ENDLOOP.
  ENDMETHOD.
ENDCLASS.
'''

    # G) OData V4 Service Definition
    srvd_source = f'''@EndUserText.label: '{display_name} - Service Definition'
define service {service_def} {{
  expose {cds_proj} as PassRequest;
  expose {cds_item_proj} as PassItem;
}}
'''

    # H) Authorization Check Class
    auth_class_source = f'''CLASS {auth_class} DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    CLASS-METHODS check_authorization
      IMPORTING
        iv_activity TYPE activ_auth
        iv_plant    TYPE werks_d OPTIONAL
      RETURNING
        VALUE(rv_authorized) TYPE abap_bool.
ENDCLASS.

CLASS {auth_class} IMPLEMENTATION.
  METHOD check_authorization.
    AUTHORITY-CHECK OBJECT 'Z_GP_AUTH'
      ID 'ACTVT' FIELD iv_activity
      ID 'WERKS' FIELD iv_plant.
    rv_authorized = COND #( WHEN sy-subrc = 0 THEN abap_true ELSE abap_false ).
  ENDMETHOD.
ENDCLASS.
'''

    # -------------------------------------------------------------
    # Documentation & Alignment Files
    # -------------------------------------------------------------

    # 1. FSD Alignment Matrix
    fsd_alignment_rows = []
    for sc in screens:
        sid = _clean_text(sc.get("screen_id"))
        sname = _clean_text(sc.get("name"))
        floorplan = _clean_text(sc.get("floorplan") or sc.get("proposed_technology"))
        fsd_alignment_rows.append(f"| `{sid}` | **{sname}** | {floorplan} | `fiori/webapp/view/{sid}.view.xml` | `{cds_proj}` / `{service_def}` |")

    fsd_alignment_md = f'''# FSD-to-Starter Code Alignment Matrix — {display_name}

Generated on {generated_at} from the approved Business Requirements Document (BRD) and Functional Specification (FSD).

## 1. SAP Fiori Screen Mapping

| FSD Screen | Screen Name | Proposed Technology / Floorplan | Fiori View & Controller | Backend CDS & OData Service |
|---|---|---|---|---|
{chr(10).join(fsd_alignment_rows) if fsd_alignment_rows else "| `SCR-01` | Supplier Purchase Orders | SAP Fiori elements - List Report | `view/ListReport.view.xml` | `ZC_GatePass_C` |"}
| `SCR-02` | Request Entry & PO Object Page | SAP Fiori elements - Object Page | `view/RequestEntry.view.xml` | `ZI_GatePass_R` / Draft BDEF |
| `SCR-04` | My Inbox: Level 1 Review | SAPUI5 Freestyle / SplitApp | `view/ApprovalInbox.view.xml` | `approveRequest`, `rejectRequest` |
| `SCR-06` | Approved Pass Download | SAP Fiori elements - Object Page | `view/PassDownload.view.xml` | Cryptographic QR Generator |
| `SCR-07` | Gate Verification Scanner | SAPUI5 Mobile / Viewfinder | `view/GateVerification.view.xml` | `admitVehicle`, `denyEntry` |

## 2. Business Process Sequence

| Step | Actor | Action / Rule | Implementation Object |
|---|---|---|---|
| **PS-01** | Supplier Requester | Search & select eligible PO | `ListReport.controller.js` / FilterBar |
| **PS-02** | Supplier Requester | Enter transporter details & submit | `RequestEntry.controller.js` / BDEF Validations |
| **PS-03** | Level 1 Approver | Operational review in My Inbox | `ApprovalInbox.controller.js` / `approveRequest` |
| **PS-04** | Level 2 Approver | Final security authorization | `ApprovalInbox.controller.js` / `approveRequest` |
| **PS-05** | System / Supplier | Generate immutable QR pass | `PassDownload.controller.js` / PDF Generator |
| **PS-06** | Gate Security | Scan QR and Admit / Deny | `GateVerification.controller.js` / `admitVehicle` |
'''

    # 2. Data Model Documentation
    data_model_md = f'''# Data Model Specification — {display_name}

## 1. Core Data Services (CDS) Entities

- **Root Entity**: `{cds_root}` (`zt{slug[:8].replace("-", "_")}_head`)
  - Key: `PassUUID` (UUID 16/36)
  - Fields: `RequestNumber`, `PONumber`, `SupplierCode`, `SupplierName`, `Plant`, `VehicleNumber`, `DriverName`, `DriverMobile`, `DeliveryNote`, `RequestedEntryDate`, `TimeSlot`, `GateBay`, `Status`, `QRToken`.
- **Item Entity**: `{cds_item}` (`zt{slug[:8].replace("-", "_")}_item`)
  - Key: `ItemUUID`
  - Composition Parent: `PassUUID`
  - Fields: `ItemNumber`, `MaterialCode`, `MaterialName`, `Quantity`, `Unit`.
- **Projection Views**: `{cds_proj}` and `{cds_item_proj}`.
- **Metadata Extension**: `{mde_name}.mde.asddls`.
'''

    # 3. API Contract Documentation
    api_contract_md = f'''# OData V4 API Contract — {display_name}

**Service Name**: `{service_def}`  
**Protocol**: OData V4  
**Base URI**: `/sap/opu/odata4/sap/{service_def.lower()}/srvd/sap/{service_def.lower()}/0001/`

## EntitySets
- `PassRequest`: `GET, POST, PATCH, DELETE`
- `PassItem`: `GET, POST, PATCH, DELETE`

## Bound Actions
1. `PassRequest/approveRequest`: Approves request and generates cryptographic QR token.
2. `PassRequest/rejectRequest`: Formal rejection with mandatory reason parameter.
3. `PassRequest/returnToSupplier`: Return for correction with mandatory comment.
4. `PassRequest/admitVehicle`: Gate entry authorization event.
5. `PassRequest/denyEntry`: Gate entry refusal with incident logging.
'''

    # 4. Security Guidelines
    security_md = f'''# Security Architecture & Authorization — {display_name}

1. **Backend Authorization**: All operations enforce `AUTHORITY-CHECK OBJECT 'Z_GP_AUTH'` inside `{auth_class}`.
2. **Cryptographic QR Verification**: Digital signatures on the pass token prevent tampering.
3. **Minimum Disclosure**: Handheld gate scanners display masked vehicle plates (`MH-12-AB-****`) and masked driver names (`J*** D**`) to prevent unauthorized data exposure.
4. **Clean Core Compliance**: No direct unreleased SAP table modifications; full compliance with ABAP Cloud and managed RAP standards.
'''

    # 5. README.md
    readme_md = f'''# {display_name} — End-to-End SAP Fiori & ABAP Starter Package

Generated from **{len(requirements)} approved requirements** and the generated **Functional Specification (FSD)** on {generated_at}.

## Directory Structure

```text
├── fiori/                        # SAP Fiori Web Application
│   ├── webapp/
│   │   ├── manifest.json         # UI5 Application Descriptor with full routing
│   │   ├── Component.js          # Component definition & router init
│   │   ├── index.html            # Shell bootstrap (Horizon theme)
│   │   ├── view/                 # XML Views mirroring FSD screens
│   │   │   ├── App.view.xml      # ToolPage Shell & SideNavigation
│   │   │   ├── ListReport.view.xml       # SCR-01: Supplier PO List Report
│   │   │   ├── RequestEntry.view.xml     # SCR-02: Gate Pass Request Object Page
│   │   │   ├── ApprovalInbox.view.xml    # SCR-04/05: SplitApp Approver Inbox
│   │   │   ├── GateVerification.view.xml # SCR-07: Handheld Mobile QR Scanner
│   │   │   └── PassDownload.view.xml     # SCR-06: Approved Pass Download Card
│   │   ├── controller/           # JavaScript Controllers with validation logic
│   │   ├── model/
│   │   │   └── mockData.json     # Realistic BRD-grounded mock dataset
│   │   ├── i18n/
│   │   │   └── i18n.properties  # Localized text bundles
│   │   └── css/style.css         # Horizon styling & scanner animations
│   ├── ui5.yaml                  # UI5 CLI configuration
│   └── package.json              # NPM dependencies & scripts
├── abap/                         # ABAP Cloud & RAP Backend Services
│   ├── src/
│   │   ├── cds/                  # Core Data Services (Root, Item, Projections, MDE)
│   │   ├── rap/                  # Managed Behavior Definition & Behavior Pool
│   │   ├── srv/                  # OData V4 Service Definition
│   │   └── sec/                  # Central Authorization Class
│   └── README.md                 # ADT setup and activation instructions
└── docs/                         # Specifications & Traceability
    ├── FSD_ALIGNMENT.md          # Screen-by-screen FSD mapping
    ├── DATA_MODEL.md             # CDS Data dictionary & entity relations
    ├── API_CONTRACT.md           # OData V4 entitysets & action definitions
    ├── SECURITY.md               # Security controls & authorization checks
    └── requirements.json         # Approved requirements snapshot
```

## Running the Fiori Application Locally

```bash
cd fiori
npm install
npm start
```
'''

    # Combine all files into the dictionary
    files: dict[str, str] = {
        "README.md": readme_md,
        "docs/FSD_ALIGNMENT.md": fsd_alignment_md,
        "docs/DATA_MODEL.md": data_model_md,
        "docs/API_CONTRACT.md": api_contract_md,
        "docs/SECURITY.md": security_md,
        "docs/requirements.json": json.dumps(mock_data, ensure_ascii=False, indent=2),
        "fiori/package.json": json.dumps(package_json, indent=2),
        "fiori/ui5.yaml": ui5_yaml,
        "fiori/webapp/index.html": index_html,
        "fiori/webapp/manifest.json": json.dumps(manifest, indent=2),
        "fiori/webapp/Component.js": component_js,
        "fiori/webapp/view/App.view.xml": app_view,
        "fiori/webapp/controller/App.controller.js": app_controller,
        "fiori/webapp/view/ListReport.view.xml": list_report_view,
        "fiori/webapp/controller/ListReport.controller.js": list_report_controller,
        "fiori/webapp/view/RequestEntry.view.xml": request_entry_view,
        "fiori/webapp/controller/RequestEntry.controller.js": request_entry_controller,
        "fiori/webapp/view/ApprovalInbox.view.xml": approval_inbox_view,
        "fiori/webapp/controller/ApprovalInbox.controller.js": approval_inbox_controller,
        "fiori/webapp/view/GateVerification.view.xml": gate_verification_view,
        "fiori/webapp/controller/GateVerification.controller.js": gate_verification_controller,
        "fiori/webapp/view/PassDownload.view.xml": pass_download_view,
        "fiori/webapp/controller/PassDownload.controller.js": pass_download_controller,
        "fiori/webapp/model/mockData.json": json.dumps(mock_data, ensure_ascii=False, indent=2),
        "fiori/webapp/i18n/i18n.properties": i18n_properties,
        "fiori/webapp/css/style.css": css_style,
        f"abap/src/cds/{cds_root.lower()}.ddls.asddls": cds_root_source,
        f"abap/src/cds/{cds_item.lower()}.ddls.asddls": cds_item_source,
        f"abap/src/cds/{cds_proj.lower()}.ddls.asddls": cds_proj_source,
        f"abap/src/cds/{cds_item_proj.lower()}.ddls.asddls": cds_item_proj_source,
        f"abap/src/cds/{mde_name.lower()}.mde.asddls": mde_source,
        f"abap/src/rap/{bdef_name.lower()}.bdef.asbdef": bdef_source,
        f"abap/src/rap/{behavior_class.lower()}.clas.abap": behavior_class_source,
        f"abap/src/rap/{behavior_class.lower()}.clas.locals_imp.abap": behavior_class_local_source,
        f"abap/src/srv/{service_def.lower()}.srvd.asapsrvd": srvd_source,
        f"abap/src/sec/{auth_class.lower()}.clas.abap": auth_class_source,
        f"abap/src/{class_name.lower()}.clas.abap": f'''CLASS {class_name} DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    INTERFACES {interface_name}.
  PRIVATE SECTION.
    METHODS validate_authorization.
ENDCLASS.

CLASS {class_name} IMPLEMENTATION.
  METHOD {interface_name}~get_requirements.
    validate_authorization( ).
    " Dispatches request to RAP Root entity {cds_root} via EML
    result = VALUE #( ).
  ENDMETHOD.

  METHOD validate_authorization.
    {auth_class}=>check_authorization( iv_activity = '03' ).
  ENDMETHOD.
ENDCLASS.
''',
        f"abap/src/{interface_name.lower()}.intf.abap": f'''INTERFACE {interface_name} PUBLIC.
  TYPES: BEGIN OF ty_requirement,
           requirement_key TYPE string,
           title           TYPE string,
           priority        TYPE string,
           status          TYPE string,
         END OF ty_requirement,
         tt_requirements TYPE STANDARD TABLE OF ty_requirement WITH EMPTY KEY.

  METHODS get_requirements
    RETURNING VALUE(result) TYPE tt_requirements.
ENDINTERFACE.
''',
        "abap/README.md": f"# ABAP Cloud & RAP Setup for {display_name}\n\n1. Import the CDS and RAP artifacts into ADT under customer package `Z{suffix[:8]}`.\n2. Activate Behavior Definition `{bdef_name}`.\n3. Publish OData V4 Service Binding `{service_def}`.\n",
    }

    with tempfile.TemporaryDirectory(prefix="starter-code-", dir=output_dir) as temporary:
        root = Path(temporary) / root_name
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, f"{root_name}/{path.relative_to(root).as_posix()}")

    return {
        "status": "generated",
        "generated_at": generated_at,
        "requirement_count": len(requirements),
        "file_count": len(files),
        "zip_path": str(output_path),
        "download": f"/api/projects/{project.id}/artifacts/technical_design/starter-code/download",
        "root_folder": root_name,
        "abap_class": behavior_class,
        "abap_interface": service_def,
    }
