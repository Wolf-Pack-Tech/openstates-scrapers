import json
from pathlib import Path
import typing

from spatula.pages import JsonListPage, SkipItem
from spatula.sources import URL

from openstates.models import ScrapePerson
from openstates.models.people import PartyName, RoleType
from openstates.utils.scrape import read_gql_file


def graphql_query(data) -> URL:
    return URL(
        "https://gql.api.alison.legislature.state.al.us/graphql",
        method="POST",
        headers={
            "Content-Type": "application/json",
            # Referer required or graphql will respond with http error 403
            "Referer": "https://alison.legislature.state.al.us/",
        },
        data=json.dumps(data), # type: ignore - str is allowed underneath
    )


def get_members_source() -> URL:
    return graphql_query(
        {
            "operationName": "legislativeMembers",
            "query": read_gql_file(Path(__file__).parent / "people.gql"),
            "variables": {},
        },
    )


class MemberList(JsonListPage):
    source = get_members_source()

    def process_page(self) -> typing.Iterable[typing.Any]:
        yield from self._process_or_skip_loop(self.data["data"]["legislativeMembers"]["data"])

    def process_item(self, item):
        # Skip adding member if district info isn't found.
        if item["district"] == "Not Available":
            name = item["fullName"]
            raise SkipItem(f"{name} has no listed district, skipping.")

        # Use just the district number
        district = item["district"].split(" ")[-1]

        if item["fullName"] == "Vacant":
            raise SkipItem(f"{district} is vacant, skipping.")

        # The API's Afilliation enum currently only has "D" and "R".
        # This should fail as we learn of other possible values.
        party = {
            "D": PartyName.DEM,
            "R": PartyName.REP
        }[item["affiliation"]]

        chamber = {
            "House": RoleType.LOWER,
            "Senate": RoleType.UPPER,
        }[item["body"]]

        p = ScrapePerson(
            name=item["fullName"],
            state="al",
            party=party,
            district=district,
            chamber=chamber,
            image=item["imageUrl"],
            email=item["email"] or "",
            given_name=item["firstName"],
            family_name=item["lastName"],
        )

        p.add_source(
            str(self.source),
            note="graphql endpoint for member information"
        )

        # Member profiles can't be access by url alone, so add homepage links
        # for house/senate list page instead
        if chamber == RoleType.UPPER:
            # Senate member list
            p.add_link(
                "https://alison.legislature.state.al.us/senate-leaders-members",
                note="homepage",
            )
        elif chamber == RoleType.LOWER:
            # House member list
            p.add_link(
                "https://alison.legislature.state.al.us/house-leaders-members",
                note="homepage",
            )

        # Missing data may sometimes be set to a string like "None Listed"
        capitol_address = item["fullAddress"]
        if not capitol_address.startswith("No Address Listed"):
            p.capitol_office.address = capitol_address.strip().replace("\n", ", ")

        capitol_phone = item["phone"]
        if capitol_phone and not capitol_phone == "None Listed":
            p.capitol_office.voice = capitol_phone

        capitol_fax = item["fax"]
        if capitol_fax:
            p.capitol_office.fax = capitol_fax

        district_address = item["fullDistrictAddress"]
        if not district_address.startswith("No District Address Listed"):
            p.district_office.address = district_address.strip().replace("\n", ", ")

        district_phone = item["districtPhone"]
        if district_phone and not district_phone == "None Listed":
            p.district_office.voice = district_phone

        district_fax = item["districtFax"]
        if district_fax:
            p.district_office.fax = district_fax

        p.extras["counties"] = item["counties"]

        leadership_title = item["leadershipTitle"]
        if leadership_title:
            p.extras["title"] = leadership_title

        return p
