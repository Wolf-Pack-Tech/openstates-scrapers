from spatula.pages import JsonListPage, HtmlPage, SkipItem
from spatula.selectors import CSS, XPath

from openstates.models import ScrapePerson
from openstates.models.people import PartyName, RoleType
from openstates.utils.scrape import infer_name_parts


class ExtraDetail(HtmlPage):
    def process_page(self):
        subtitle = CSS("#content h1 + *").match_one(self.root).text_content().strip()
        if "Deceased" in subtitle:
            raise SkipItem("Member is deceased")

        if "Resigned" in subtitle:
            raise SkipItem("Member has resigned")

        biography_link = XPath(
            ".//div[@id='tableDataWrapper']"
            "//div[contains(@class, 'row')]"
            "//div[normalize-space(.)='Biography:']"
            "//following-sibling::div[1]//a/@href"
        ).match(self.root, min_items=0)
        if biography_link:
            self.input.extras["biography"] = biography_link[0]

        return self.input


class PeopleList(JsonListPage):
    chamber: RoleType

    def get_source_from_input(self):
        chamber = {
            RoleType.UPPER: "Senate",
            RoleType.LOWER: "House",
        }[self.chamber]

        return (
            "https://services2.arcgis.com/wu7u046EJ59dJv3h/arcgis/rest/services/"
            f"Arkansas%20State%20{chamber}/FeatureServer/0/query"
            "?f=json&outFields=*&spatialRel=esriSpatialRelIntersects&where=1%20=%201"
        )

    def postprocess_response(self):
        super().postprocess_response()
        self.data = self.data["features"]

    def process_item(self, item):
        attributes = item["attributes"]

        name = " ".join([attributes["FirstName"], attributes["LastName"]])

        party = {
            "D": PartyName.DEM,
            "R": PartyName.REP,
            "G": PartyName.GREEN,
            "I": PartyName.IND,
        }.get(attributes["Party"])
        if not party:
            raise SkipItem(f"Unknown party abbreviation: {attributes['Party']}")

        chamber = {
            "Senate": RoleType.UPPER,
            "House": RoleType.LOWER,
        }.get(attributes["Chamber"])
        if not chamber:
            raise SkipItem(f"Unknown chamber title: {attributes['Chamber']}")

        p = ScrapePerson(
            name=name,
            state="ar",
            party=party,
            district=attributes["district"],
            chamber=chamber,
            image=attributes["PhotoURL"],
            email=attributes["Email"],
            # given_name=attributes["FirstName"],  # Includes middle name/initial and sometimes a prefix
            # family_name=attributes["LastName"],  # Includes suffixes
            # suffix="",  # No suffix info available separately
        )
        infer_name_parts(p)

        p.add_source(str(self.source), "member list JSON")
        p.add_source(attributes["MemberURL"], "member detail page")

        p.add_link("https://www.arkleg.state.ar.us/Legislators/List", "member list page")
        p.add_link(attributes["MemberURL"], "member detail page")
        member_source = (
            "https://services2.arcgis.com/wu7u046EJ59dJv3h/arcgis/rest/services/"
            f"Arkansas%20State%20{attributes['Chamber']}/FeatureServer/0/query"
            f"?f=json&outFields=*&where=districtn={attributes['district']}"
        )
        p.add_link(member_source, "member detail JSON")

        # Individual rooms aren't listed; using general capitol address
        p.capitol_office.address = "1 Capitol Mall, Fifth Floor, Little Rock, AR 72201"

        if attributes["Address"]:
            p.district_office.address = f"{attributes['Address']}, {attributes['City']}, AR {attributes['Zip']}"
        p.district_office.voice = attributes["Phone"]

        # Extras
        if attributes["Senior"]:
            p.extras["seniority"] = attributes["Senior"]
        if attributes["Occupation"]:
            p.extras["occupation"] = attributes["Occupation"]
        if attributes["ChurchAffiliation"]:
            p.extras["church"] = attributes["ChurchAffiliation"]
        if attributes["PublicService"]:
            p.extras["public_service"] = attributes["PublicService"]
        if attributes["Veteran"]:
            p.extras["veteran"] = True if attributes["Veteran"].lower() == "yes" else False

        p = ExtraDetail(p, source=attributes["MemberURL"])

        return p


class SenatorList(PeopleList):
    chamber = RoleType.UPPER


class RepresentativeList(PeopleList):
    chamber = RoleType.LOWER