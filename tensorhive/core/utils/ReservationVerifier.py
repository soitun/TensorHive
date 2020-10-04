from datetime import time, timedelta
from sqlalchemy.orm.exc import NoResultFound
from tensorhive.models.Resource import Resource


class ReservationVerifier:
    @classmethod
    def __get_latest_date_allowed_by_schedules(cls, start_date, end_date, schedules):
        """
        Check if schedules allow for reservation between start_date and end_date and returns the latest date
        (starting from start_date) that schedules allow
        :param start_date: Reservation start date
        :param end_date: Reservation end date
        :param schedules: Schedule list that is checked to determine if reservation is allowed
        :return: latest date starting from start_date allowed by given schedules
        """
        reservation_allowed = False
        while True:
            start_date_changed = False
            for schedule in schedules:
                day = start_date.weekday() + 1
                if str(day) in schedule.schedule_days and schedule.hour_start <= start_date.time():
                    if schedule.hour_end == time(hour=23, minute=59):
                        start_date = start_date.replace(hour=0, minute=0) + timedelta(days=1)
                    elif start_date.time() < schedule.hour_end:
                        start_date = start_date.replace(hour=schedule.hour_end.hour, minute=schedule.hour_end.minute)
                    else:
                        continue
                    start_date_changed = True
                    if start_date >= end_date:
                        reservation_allowed = True
                        break
            if reservation_allowed or not start_date_changed:
                break
        return start_date

    @classmethod
    def is_reservation_allowed(cls, user, reservation):
        """
        Check if reservation is allowed with restrictions of given user
        :param user: user to whom reservation belongs
        :param reservation: reservation to be checked
        :return: True if reservation is allowed, False otherwise
        """
        try:
            resource = Resource.get(reservation.protected_resource_id)
        except NoResultFound:
            return False

        user_restrictions = user.get_restrictions(include_group=True)
        # get global restrictions or applied to selected resource
        restrictions = [r for r in user_restrictions if r.is_global or resource in r.resources]

        # time interval required to create restriction
        start_date = reservation.starts_at
        end_date = reservation.ends_at

        reservation_allowed = False
        while True:
            start_date_changed = False
            for restriction in restrictions:
                if restriction.starts_at <= start_date and \
                        (restriction.ends_at is None or start_date < restriction.ends_at):
                    schedules = restriction.schedules
                    if not schedules:
                        start_date = restriction.ends_at
                        start_date_changed = True
                    else:
                        date = cls.__get_latest_date_allowed_by_schedules(start_date, end_date, schedules)
                        if date > start_date:
                            start_date_changed = True
                            start_date = date
                    if start_date >= end_date:
                        reservation_allowed = True
                        break
            if reservation_allowed or not start_date_changed:
                break
        return reservation_allowed

    @classmethod
    def update_user_reservations_statuses(cls, user, have_users_permissions_increased):
        """
        Updates reservations statuses (is_cancelled) affected by change in user permissions
        :param user: user whose permissions have changed
        :param have_users_permissions_increased: if set to True, signifies that user's permissions
         have recently widened, otherwise signifies that user's permissions have recently shrunk
        """
        reservations = user.get_reservations(include_cancelled=True)
        for reservation in reservations:
            if have_users_permissions_increased:
                if reservation.is_cancelled and cls.is_reservation_allowed(user, reservation) \
                        and not reservation.would_interfere():
                    reservation.is_cancelled = False
                    reservation.save()
            else:
                if not reservation.is_cancelled and not cls.is_reservation_allowed(user, reservation):
                    reservation.is_cancelled = True
                    reservation.save()
